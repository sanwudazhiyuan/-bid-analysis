"""暗标审查引擎：格式规则审查 + 内容规则审查。"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from src.extractor.base import call_qwen, build_messages
from src.models import Paragraph, DocumentFormat
from src.reviewer.anbiao_rule_parser import AnbiaoRule

logger = logging.getLogger(__name__)


@dataclass
class ChapterBatch:
    """单个章节审核批次。

    - text: 段落拼接文本（含 [p.index] 前缀）
    - para_indices: 批次包含的全局段落索引
    - chapter_title: 章节标题；兜底模式为 "段落批次 N"
    - image_map: 批次专属 filename→绝对路径 映射
    """
    text: str
    para_indices: list[int]
    chapter_title: str
    image_map: dict[str, str] = field(default_factory=dict)


_FORMAT_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "anbiao_format_review.txt"
_CONTENT_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "anbiao_content_review.txt"
_CONTENT_CONCLUDE_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "anbiao_content_review_conclude.txt"

_MAX_IMAGES_PER_SUB_BATCH = 6


def _collect_leaf_chapters(chapters: list[dict], max_level: int = 3) -> list[dict]:
    """递归展开章节树，收集叶子节点。

    - 无 children 的节点：叶子
    - level >= max_level 的节点：叶子（其 children 不再展开，自身整体作为一个批次）
    - 其余：继续递归 children
    """
    leaves = []
    for ch in chapters:
        children = ch.get("children", [])
        level = ch.get("level", 1)
        if not children or level >= max_level:
            leaves.append(ch)
        else:
            leaves.extend(_collect_leaf_chapters(children, max_level))
    return leaves


def _filter_images_for_batch(
    para_indices: list[int],
    extracted_images: list[dict],
) -> dict[str, str]:
    """筛选段落范围内的图片，返回 filename→path。

    img['path'] 已经是完整路径（image_extractor.py 中构建），无需再拼接。
    """
    batch_para_set = set(para_indices)
    image_map: dict[str, str] = {}
    for img in extracted_images:
        near_indices = img.get("near_para_indices")
        if not near_indices:
            single = img.get("near_para_index")
            near_indices = [single] if single is not None else []
        if any(pi in batch_para_set for pi in near_indices):
            image_map[img["filename"]] = img["path"]
    return image_map


def _build_batch_from_node(
    node: dict,
    paragraphs: list,
    extracted_images: list[dict],
    title: str,
) -> ChapterBatch:
    """从章节节点构建 ChapterBatch（用于叶子节点整体发送 + 云端超限子章节拆分）。"""
    from src.reviewer.tender_indexer import paragraphs_to_text
    start = node.get("start_para", 0)
    end = node.get("end_para", len(paragraphs) - 1 if paragraphs else 0)
    paras = [p for p in paragraphs if start <= p.index <= end]
    text = paragraphs_to_text(paras)
    indices = [p.index for p in paras]
    img_map = _filter_images_for_batch(indices, extracted_images)
    return ChapterBatch(text=text, para_indices=indices, chapter_title=title, image_map=img_map)


def _build_fallback_batches(
    paragraphs: list,
    image_map: dict[str, str] | None,
    extracted_images: list[dict] | None = None,
    batch_size: int = 50,
) -> list[ChapterBatch]:
    """无章节索引时按段落数分批，chapter_title 为 "段落批次 N"。

    优先用 extracted_images + _filter_images_for_batch 按段落范围精确分配图片；
    仅当 extracted_images 不可用时，共享传入的完整 image_map。
    """
    from src.reviewer.tender_indexer import paragraphs_to_text
    batches: list[ChapterBatch] = []
    for i in range(0, len(paragraphs), batch_size):
        batch_paras = paragraphs[i:i + batch_size]
        text = paragraphs_to_text(batch_paras)
        indices = [p.index for p in batch_paras]
        if extracted_images:
            img = _filter_images_for_batch(indices, extracted_images)
        else:
            img = dict(image_map) if image_map else {}
        batches.append(ChapterBatch(
            text=text,
            para_indices=indices,
            chapter_title=f"段落批次 {i // batch_size + 1}",
            image_map=img,
        ))
    return batches


def _split_chapter_at_sub_sections(
    chapter: dict,
    paragraphs: list,
    extracted_images: list[dict],
    max_chars: int,
) -> list[ChapterBatch]:
    """一级标题超限时在二级子章节边界切分。

    - 无子章节 → 整体作为 1 批
    - 累积超 max_chars → 提交当前累积，新批次从触发子章节开始
    - 单个子章节超 max_chars → 单独作为 1 批，title 拼为 "父/子"
    """
    from src.reviewer.tender_indexer import paragraphs_to_text

    sub_sections = chapter.get("children", [])
    if not sub_sections:
        return [_build_batch_from_node(chapter, paragraphs, extracted_images, chapter["title"])]

    batches: list[ChapterBatch] = []
    current_text_parts: list[str] = []
    current_indices: list[int] = []

    def _flush():
        if not current_text_parts:
            return
        text = "\n".join(current_text_parts)
        img_map = _filter_images_for_batch(current_indices, extracted_images)
        batches.append(ChapterBatch(
            text=text,
            para_indices=list(current_indices),
            chapter_title=chapter["title"],
            image_map=img_map,
        ))

    for sub in sub_sections:
        start = sub.get("start_para", 0)
        end = sub.get("end_para", start)
        paras_in_sub = [p for p in paragraphs if start <= p.index <= end]
        sub_text = paragraphs_to_text(paras_in_sub)
        sub_indices = [p.index for p in paras_in_sub]
        sub_chars = len(sub_text)

        if sub_chars > max_chars:
            _flush()
            current_text_parts = []
            current_indices = []
            title = chapter["title"] + "/" + sub.get("title", "")
            batches.append(_build_batch_from_node(sub, paragraphs, extracted_images, title))
            continue

        combined_len = len("\n".join(current_text_parts + [sub_text]))
        if combined_len > max_chars:
            _flush()
            current_text_parts = [sub_text]
            current_indices = list(sub_indices)
        else:
            current_text_parts.append(sub_text)
            current_indices.extend(sub_indices)

    _flush()
    return batches


def _build_chapter_batches(
    paragraphs: list,
    is_local_mode: bool,
    extracted_images: list[dict],
    image_map: dict[str, str] | None,
) -> list[ChapterBatch]:
    """按段落分批：云端50段落一批次，本地30段落一批次。"""
    batch_size = 30 if is_local_mode else 50
    return _build_fallback_batches(paragraphs, image_map, extracted_images=extracted_images, batch_size=batch_size)


def _format_chapter_results(chapter_results: list[dict]) -> str:
    """将逐章节审核结果格式化为综合判定 prompt 的输入文本。"""
    lines: list[str] = []
    for cr in chapter_results:
        lines.append(f"### 章节：{cr['chapter_title']}")
        candidates = cr.get("candidates") or []
        if candidates:
            for c in candidates:
                if not isinstance(c, dict):
                    continue
                sev = c.get("severity")
                sev_tag = f" [{sev}]" if sev else ""
                reason = c.get("reason", "")
                path = c.get("identification_path", "")
                line = f"- 段落{c.get('para_index', '?')}{sev_tag}: {reason}"
                if path:
                    line += f" | 路径: {path}"
                lines.append(line)
        else:
            lines.append("（无违规内容）")
        summary = cr.get("summary", "")
        if summary:
            lines.append(f"摘要: {summary}")
        lines.append("")
    return "\n".join(lines)


def _split_batch_by_image_limit(batch: ChapterBatch) -> list[ChapterBatch]:
    """将图片超限的 ChapterBatch 拆分为多个子批次，每批次不超过 _MAX_IMAGES_PER_SUB_BATCH 张图片。

    拆分规则：
    - 在文本中找到所有 [图片: xxx] 标记所在的段落行
    - 每6张图片一组，在包含超额图片的段落行前截断
    - 无图片的前导段落在第一个子批次中完整保留
    - 子批次的 para_indices 从行前缀 [N] 提取
    - 每个子批次带对应的 image_map 子集
    - 如果不超过6张图片，返回原 batch 不拆分
    """
    if len(batch.image_map) <= _MAX_IMAGES_PER_SUB_BATCH:
        return [batch]

    from src.reviewer.reviewer import _IMAGE_MARKER_RE as IMG_RE

    lines = batch.text.split("\n")
    # 找出每个包含图片标记的行索引及涉及的图片文件名
    image_line_map: list[tuple[int, list[str]]] = []  # (line_idx, [filenames])
    for line_idx, line in enumerate(lines):
        filenames = [m.group(1).strip() for m in IMG_RE.finditer(line)]
        if filenames:
            image_line_map.append((line_idx, filenames))

    # 为每个 image_line_map 条目记录其图片累积计数（从0开始）
    # 用来判断截断位置
    sub_batches: list[ChapterBatch] = []
    current_start_line = 0
    current_img_count = 0
    # 已分配到当前子批次的 image_line_map 条目范围
    current_entry_start = 0

    def _extract_para_indices(text_lines: list[str]) -> list[int]:
        indices = []
        for l in text_lines:
            m = re.match(r"\[(\d+)\]", l)
            if m:
                indices.append(int(m.group(1)))
        return indices

    def _collect_images(entry_start: int, entry_end: int) -> dict[str, str]:
        imgs = {}
        for _, fns in image_line_map[entry_start:entry_end]:
            for fn in fns:
                if fn in batch.image_map:
                    imgs[fn] = batch.image_map[fn]
        return imgs

    for entry_idx, (line_idx, filenames) in enumerate(image_line_map):
        n_new_images = len(filenames)
        if current_img_count + n_new_images > _MAX_IMAGES_PER_SUB_BATCH and current_img_count > 0:
            # 截断：当前子批次从 current_start_line 到 line_idx - 1
            sub_lines = lines[current_start_line:line_idx]
            sub_text = "\n".join(sub_lines) if sub_lines else ""
            sub_images = _collect_images(current_entry_start, entry_idx)
            sub_indices = _extract_para_indices(sub_lines)

            sub_batches.append(ChapterBatch(
                text=sub_text,
                para_indices=sub_indices,
                chapter_title=batch.chapter_title,
                image_map=sub_images,
            ))
            # 新子批次从当前行开始
            current_start_line = line_idx
            current_img_count = n_new_images
            current_entry_start = entry_idx
        else:
            current_img_count += n_new_images

    # 最后一批：从 current_start_line 到末尾
    if current_start_line < len(lines):
        sub_lines = lines[current_start_line:]
        sub_text = "\n".join(sub_lines)
        sub_images = _collect_images(current_entry_start, len(image_line_map))
        sub_indices = _extract_para_indices(sub_lines)
        sub_batches.append(ChapterBatch(
            text=sub_text,
            para_indices=sub_indices,
            chapter_title=batch.chapter_title,
            image_map=sub_images,
        ))

    if len(sub_batches) <= 1:
        return [batch]

    logger.info("_split_batch_by_image_limit: 章节=%s, 图片=%d, 拆为%d个子批次",
                batch.chapter_title, len(batch.image_map), len(sub_batches))
    return sub_batches


def review_format_rules(
    rules: list[AnbiaoRule],
    doc_format: DocumentFormat,
    paragraphs: list[Paragraph],
    api_settings: dict,
    is_local_mode: bool = False,
) -> list[dict]:
    """逐条格式规则调 LLM 判断。返回 [{rule_index, rule_text, result, reason, details}]。"""
    prompt_template = _FORMAT_PROMPT_PATH.read_text(encoding="utf-8")
    doc_format_text = doc_format.to_prompt_text()
    results = []

    def _review_one(rule: AnbiaoRule) -> dict:
        severity_level = "mandatory" if rule.is_mandatory else "advisory"
        prompt = (
            prompt_template
            .replace("{rule_text}", rule.rule_text)
            .replace("{severity_level}", severity_level)
            .replace("{document_format_text}", doc_format_text)
        )
        messages = build_messages(system="你是暗标格式审查专家。", user=prompt)
        # 审查阶段：本地300s，云端180s
        review_settings = api_settings if is_local_mode else {
            **api_settings, "api": {**api_settings.get("api", {}), "timeout": 180}}
        llm_result = call_qwen(messages, review_settings)

        if not isinstance(llm_result, dict):
            return {
                "rule_index": rule.rule_index,
                "rule_text": rule.rule_text,
                "rule_type": "format",
                "result": "error",
                "reason": "LLM 调用失败",
                "details": [],
                "is_mandatory": rule.is_mandatory,
            }

        result_val = llm_result.get("result", "error")
        # 非强制规则：fail 降级为 warning
        if not rule.is_mandatory and result_val == "fail":
            result_val = "warning"

        return {
            "rule_index": rule.rule_index,
            "rule_text": rule.rule_text,
            "rule_type": "format",
            "result": result_val,
            "reason": llm_result.get("reason", ""),
            "details": llm_result.get("details", []),
            "is_mandatory": rule.is_mandatory,
        }

    if is_local_mode:
        for rule in rules:
            results.append(_review_one(rule))
    else:
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(_review_one, rule): rule for rule in rules}
            for future in as_completed(futures):
                results.append(future.result())

    results.sort(key=lambda r: r["rule_index"])
    return results


def review_content_rules(
    rules: list[AnbiaoRule],
    paragraphs: list[Paragraph],
    tender_index: dict,
    extracted_images: list[dict],
    doc_format: DocumentFormat,
    api_settings: dict,
    is_local_mode: bool = False,
    image_map: dict[str, str] | None = None,
    progress_callback=None,
) -> list[dict]:
    """内容规则按章节独立审核 + 综合判定。

    流程：
    1. _build_chapter_batches 产出 ChapterBatch 列表
    2. 对每条规则：对每个批次独立调 LLM（章节审核），然后一次综合判定调用
    3. 综合判定结果仅取 result/confidence/reason，tender_locations 直接从各批次 candidates 采纳
    """
    from src.reviewer.reviewer import _build_multimodal_content, _IMAGE_MARKER_RE

    content_prompt_template = _CONTENT_PROMPT_PATH.read_text(encoding="utf-8")
    conclude_prompt_template = _CONTENT_CONCLUDE_PROMPT_PATH.read_text(encoding="utf-8")

    batches = _build_chapter_batches(
        paragraphs, is_local_mode, extracted_images, image_map,
    )

    all_results: list[dict] = []
    # 预计算所有规则的子批次总数，用于进度估算
    total_work = 0
    for rule in rules:
        sub_count = 0
        for batch in batches:
            sub_count += len(_split_batch_by_image_limit(batch))
        total_work += sub_count + 1  # +1 = 综合判定
    done_work = 0

    def _review_one_sub_batch(sub: ChapterBatch, rule: AnbiaoRule, severity_level: str) -> dict:
        """审核单个子批次。返回 {chapter_title, candidates, summary}。"""
        prompt = (
            content_prompt_template
            .replace("{rule_text}", rule.rule_text)
            .replace("{severity_level}", severity_level)
            .replace("{chapter_title}", sub.chapter_title)
            .replace("{tender_text}", sub.text)
        )

        has_images = sub.image_map and _IMAGE_MARKER_RE.search(prompt)
        if has_images:
            logger.info("暗标内容审查: 章节=%s, 图片数=%d", sub.chapter_title, len(sub.image_map))
            content = _build_multimodal_content(prompt, sub.image_map)
            messages = [
                {"role": "system", "content": "你是暗标内容审查专家。"},
                {"role": "user", "content": content},
            ]
        else:
            logger.info("暗标内容审查: 章节=%s, 无图片发送", sub.chapter_title)
            messages = build_messages(system="你是暗标内容审查专家。", user=prompt)

        # 审查阶段：本地300s，云端180s
        review_settings = api_settings if is_local_mode else {
            **api_settings, "api": {**api_settings.get("api", {}), "timeout": 180}}
        llm_result = None
        for attempt in range(3):
            try:
                llm_result = call_qwen(messages, review_settings)
                if isinstance(llm_result, dict):
                    break
                logger.warning("暗标内容审查: 章节=%s, 第%d次调用返回非dict, 重试", sub.chapter_title, attempt + 1)
            except Exception as e:
                logger.warning("暗标内容审查: 章节=%s, 第%d次调用异常: %s, 重试", sub.chapter_title, attempt + 1, e)
                llm_result = None

        if not isinstance(llm_result, dict):
            return {"chapter_title": sub.chapter_title, "candidates": [], "summary": "LLM调用失败"}

        return {
            "chapter_title": sub.chapter_title,
            "candidates": llm_result.get("candidates", []) or [],
            "summary": llm_result.get("summary", ""),
        }

    for rule in rules:
        severity_level = "mandatory" if rule.is_mandatory else "advisory"

        # 构建所有子批次任务：[(batch_idx, sub_batch)]
        all_sub_tasks: list[tuple[int, ChapterBatch]] = []
        for batch_idx, batch in enumerate(batches):
            for sub in _split_batch_by_image_limit(batch):
                all_sub_tasks.append((batch_idx, sub))

        # 并发执行所有子批次：本地2线程，云端6线程
        max_workers = 2 if is_local_mode else 6
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {}
            for batch_idx, sub in all_sub_tasks:
                fut = executor.submit(_review_one_sub_batch, sub, rule, severity_level)
                future_to_task[fut] = (batch_idx, sub)
            task_results = []
            for future in as_completed(future_to_task):
                batch_idx, _ = future_to_task[future]
                task_results.append((batch_idx, future.result()))
                done_work += 1
                if progress_callback:
                    progress_callback(done_work, total_work)

        # 合并子批次结果到 chapter_results（按 batch_idx 分组）
        chapter_results: list[dict] = []
        for batch_idx, batch in enumerate(batches):
            merged_candidates: list[dict] = []
            merged_summary_parts: list[str] = []
            for bi, sr in task_results:
                if bi == batch_idx:
                    merged_candidates.extend(sr.get("candidates", []) or [])
                    if sr.get("summary"):
                        merged_summary_parts.append(sr["summary"])
            chapter_results.append({
                "chapter_title": batch.chapter_title,
                "candidates": merged_candidates,
                "summary": "; ".join(merged_summary_parts) if merged_summary_parts else "",
            })

        chapter_results_text = _format_chapter_results(chapter_results)
        prompt = (
            conclude_prompt_template
            .replace("{rule_text}", rule.rule_text)
            .replace("{severity_level}", severity_level)
            .replace("{chapter_results_text}", chapter_results_text)
        )
        # 综合判定：本地300s，云端180s
        conclude_settings = api_settings if is_local_mode else {
            **api_settings, "api": {**api_settings.get("api", {}), "timeout": 180}}
        messages = build_messages(system="你是暗标内容审查专家。", user=prompt)
        llm_result = call_qwen(messages, conclude_settings)
        done_work += 1
        if progress_callback:
            progress_callback(done_work, total_work)

        all_candidates = [
            c for cr in chapter_results for c in cr["candidates"]
            if isinstance(c, dict) and c.get("para_index") is not None
        ]

        if not isinstance(llm_result, dict):
            if all_candidates:
                result_val = "fail" if rule.is_mandatory else "warning"
                confidence = 60
                reason = "综合判定 LLM 调用失败，从章节候选推导（不完整结果）"
            else:
                result_val = "pass"
                confidence = 50
                reason = "综合判定 LLM 调用失败，无章节候选（低置信度通过）"
            if not rule.is_mandatory and result_val == "fail":
                result_val = "warning"
            all_results.append({
                "source_module": "anbiao",
                "clause_index": rule.rule_index,
                "clause_text": rule.rule_text,
                "rule_type": "content",
                "result": result_val,
                "confidence": confidence,
                "reason": reason,
                "severity": "critical" if rule.is_mandatory else "minor",
                "is_mandatory": rule.is_mandatory,
                "tender_locations": [],
            })
            continue

        result_val = llm_result.get("result", "error")
        if not rule.is_mandatory and result_val == "fail":
            result_val = "warning"

        # tender_locations：全部采纳各批次 candidates，不再由 conclude 筛选
        if result_val == "pass":
            tender_locations = []
        else:
            para_indices = [c["para_index"] for c in all_candidates]
            per_para_reasons = {c["para_index"]: c.get("reason", "") for c in all_candidates}
            tender_locations = [{
                "batch_id": "all_candidates",
                "path": "accumulated",
                "global_para_indices": para_indices,
                "text_snippet": all_candidates[0].get("text_snippet", "") if all_candidates else "",
                "per_para_reasons": per_para_reasons,
            }] if all_candidates else []

        all_results.append({
            "source_module": "anbiao",
            "clause_index": rule.rule_index,
            "clause_text": rule.rule_text,
            "rule_type": "content",
            "result": result_val,
            "confidence": int(llm_result.get("confidence", 0)),
            "reason": llm_result.get("reason", ""),
            "severity": "critical" if rule.is_mandatory else "minor",
            "is_mandatory": rule.is_mandatory,
            "tender_locations": tender_locations,
        })

    all_results.sort(key=lambda r: r["clause_index"])
    return all_results


def compute_anbiao_summary(format_results: list[dict], content_results: list[dict]) -> dict:
    """计算暗标审查汇总统计。"""
    all_items = format_results + content_results
    total = len(all_items)
    pass_count = sum(1 for r in all_items if r["result"] == "pass")
    fail_count = sum(1 for r in all_items if r["result"] == "fail")
    warning_count = sum(1 for r in all_items if r["result"] == "warning")
    error_count = sum(1 for r in all_items if r["result"] == "error")
    return {
        "total": total,
        "pass": pass_count,
        "fail": fail_count,
        "warning": warning_count,
        "error": error_count,
        "format_total": len(format_results),
        "content_total": len(content_results),
    }