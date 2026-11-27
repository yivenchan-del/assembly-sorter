from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import requests

from ..config import API_BASE_URL, API_HISTORY_URL, ASSEMBLY_TASK_URL
from .state_store import state_store

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}
_session = requests.Session()


def _build_headers(token: Optional[str], extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers = dict(_DEFAULT_HEADERS)
    if token:
        headers["Authorization"] = token
    if extra:
        headers.update(extra)
    return headers


def fetch_internal_id_from_cloud(pb_number: str) -> Optional[str]:
    """从上游系统搜索并获取 PB 的内部唯一 IID"""
    params_json = json.dumps(
        {
            "printing_station": "7Za3X5Qgtbv7PvFk",
            "search_batch_no": f"%{pb_number}%",
            "offset": 0,
            "limit": 20,
        },
        separators=(",", ":"),
    )
    try:
        resp = _session.get(
            API_BASE_URL,
            params={"params": params_json},
            headers=_build_headers(state_store.current_token, {"Content-Type": "application/json"}),
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict):
            return None
        batch_node = payload.get("printing_batch")
        data_list = batch_node.get("data") if isinstance(batch_node, dict) else None
        if isinstance(data_list, list) and data_list and isinstance(data_list[0], dict):
            iid = data_list[0].get("iid")
            return str(iid) if iid is not None else None
    except Exception as e:
        logger.error(f"❌ [IID 获取失败] PB {pb_number}: {e}")
    return None


def fetch_printing_id_from_barcode_cloud(bucket: str) -> Optional[str]:
    """根据条码/桶号获取排版批次 IID"""
    compact_json = json.dumps(
        {
            "barcode": bucket,
            "limit": 1,
            "offset": 0,
        },
        separators=(",", ":"),
    )
    try:
        resp = _session.get(
            API_BASE_URL,
            params={"params": compact_json},
            headers=_build_headers(state_store.current_token),
            timeout=10,
        )
        resp.raise_for_status()
        task_node = resp.json()
        if not isinstance(task_node, dict):
            return None
        batch_node = task_node.get("printing_batch")
        data_list = batch_node.get("data") if isinstance(batch_node, dict) else None
        if isinstance(data_list, list) and data_list and isinstance(data_list[0], dict):
            iid = data_list[0].get("iid")
            return str(iid) if iid else None
        return None
    except Exception as e:
        logger.error(f"❌ [装配排版信息获取失败] {bucket}: {e}")
        return None


def _fetch_npp_with_token(iid: str, printing_task_iid: str, token: Optional[str]) -> Optional[str]:
    if not token:
        logger.warning("fetch_npp failed: Authorization token is missing.")
        return None

    url = f"{API_HISTORY_URL}/{printing_task_iid}/history"
    try:
        response = _session.get(
            url,
            headers=_build_headers(token),
            timeout=10,
        )
        response.raise_for_status()
        res_json = response.json()
        if not isinstance(res_json, dict):
            return None

        printing_task = res_json.get("printing_task")
        history_list = printing_task.get("history") if isinstance(printing_task, dict) else None
        if not isinstance(history_list, list):
            return None

        for his in history_list:
            if isinstance(his, dict) and his.get("printing_batch_iid") == iid:
                reason = his.get("reason")
                return str(reason) if reason is not None else None
    except requests.exceptions.RequestException as e:
        logger.error(
            f"[printing_task_iid history Fetch Error] Request failed for "
            f"task_iid: {printing_task_iid}, batch_iid: {iid}. Error: {e}"
        )
    except Exception:
        logger.exception(
            f"[printing_task_iid history Fetch Error] Unexpected parsing error for "
            f"task_iid: {printing_task_iid}, batch_iid: {iid}"
        )
    return None


def fetch_npp(iid: str, printing_task_iid: str) -> Optional[str]:
    """查询单个打印任务在指定批次下的历史原因"""
    return _fetch_npp_with_token(iid, printing_task_iid, state_store.current_token)


def _fetch_reasons_concurrently(
    iid: str,
    task_ids_by_index: Dict[int, str],
    token: Optional[str],
    max_workers: int = 6,
) -> Dict[int, Optional[str]]:
    """并发查询各槽位对应的历史原因，按槽位下标返回结果"""
    if not task_ids_by_index:
        return {}

    results: Dict[int, Optional[str]] = {}
    unique_task_ids = set(task_ids_by_index.values())
    reason_cache: Dict[str, Optional[str]] = {}

    workers = min(max_workers, len(unique_task_ids))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_task_id = {
            executor.submit(_fetch_npp_with_token, iid, task_id, token): task_id
            for task_id in unique_task_ids
        }
        for future in as_completed(future_to_task_id):
            task_id = future_to_task_id[future]
            try:
                reason_cache[task_id] = future.result()
            except Exception as e:
                logger.error(f"[Concurrent fetch_npp Error] task_iid: {task_id}, batch_iid: {iid}: {e}")
                reason_cache[task_id] = None

    for idx, task_id in task_ids_by_index.items():
        results[idx] = reason_cache.get(task_id)

    return results


def fetch_slots_info_from_cloud(iid: str) -> Optional[List[Dict[str, Any]]]:
    """根据 IID 拉取槽位明细数据"""
    url = f"{API_BASE_URL}/{iid}"
    token = state_store.current_token
    try:
        resp = _session.get(url, headers=_build_headers(token), timeout=15)
        resp.raise_for_status()

        payload = resp.json()
        batch_node = payload.get("printing_batch") if isinstance(payload, dict) else None
        if not isinstance(batch_node, dict):
            return None

        batch_no = batch_node.get("batch_no", "")
        station_node = batch_node.get("printing_station")
        station_name = (
            station_node.get("display_name", "未知工位")
            if isinstance(station_node, dict)
            else "未知工位"
        )

        slots = batch_node.get("slots")
        if not isinstance(slots, list):
            return None

        slots_info_list: List[Dict[str, Any]] = []
        task_ids_by_index: Dict[int, str] = {}

        for idx, slot in enumerate(slots):
            if not isinstance(slot, dict):
                slots_info_list.append(create_default_printing_slot(batch_no, station_name))
                continue

            item = slot.get("printing_task")
            printing_task_id = item.get("iid", "") if isinstance(item, dict) else ""
            if printing_task_id:
                task_ids_by_index[idx] = str(printing_task_id)

            assembly_task = slot.get("assembly_task")
            sales_order = slot.get("sales_order")

            if isinstance(assembly_task, dict):
                assembly_task_id = assembly_task.get("assembly_task_id", "Non_task")
                sku_status = "empty"
            else:
                assembly_task_id = "Non_task"
                sku_status = "block"

            cancelled = False
            if isinstance(sales_order, dict):
                raw_cancelled = sales_order.get("cancelled", False)
                cancelled = raw_cancelled is True or str(raw_cancelled).lower() == "true"

            slots_info_list.append(
                {
                    "sku": "空位" if sku_status == "block" else "待确定",
                    "status": sku_status,
                    "sku_desc": "无描述",
                    "is_ring_stand": False,
                    "assembly_task_id": assembly_task_id,
                    "cancelled": cancelled,
                    "batch_no": batch_no,
                    "station": station_name,
                    "rejected_reason": None,
                }
            )

        reasons_by_index = _fetch_reasons_concurrently(iid, task_ids_by_index, token)
        for idx, reason in reasons_by_index.items():
            slots_info_list[idx]["rejected_reason"] = reason

        if len(slots_info_list) > 12:
            if all(s.get("sku") == "空位" for s in slots_info_list[12:]):
                return slots_info_list[:12]

        return slots_info_list

    except Exception as e:
        logger.error(f"❌ [明细获取失败] IID {iid}: {e}")
        return None


def create_default_printing_slot(
    batch_no: str = "", station_name: str = "Non_station"
) -> Dict[str, Any]:
    return {
        "sku": "空位",
        "status": "block",
        "sku_desc": "无描述",
        "is_ring_stand": False,
        "assembly_task_id": "Non_task",
        "cancelled": False,
        "batch_no": batch_no,
        "station": station_name,
        "rejected_reason": None,
    }


def create_default_slot(task_id: str = "Non_task") -> Dict[str, Any]:
    return {
        "sku": "空位",
        "status": "block",
        "sku_desc": "无描述",
        "is_cancelled": "false",
        "is_ring_stand": False,
        "assembly_task_id": task_id,
        "printing_batch_iid": "",
        "assembly_status": "",
    }


def fetch_accembly_slots_info_from_cloud(iid: str) -> Optional[List[Dict[str, Any]]]:
    """根据批次 IID 获取装配任务及槽位列表"""
    params_json = json.dumps(
        {
            "status": ["Pending to Assemble", "Rejected", "Completed"],
            "confirm_cancelled": False,
            "search_for_bucket": f"%{iid}%",
        },
        separators=(",", ":"),
    )
    extra_headers = {
        "Content-Type": "application/json",
        "access-control-allow-origin": "https://mps-v1-portal.casetify.com",
        "referer": "https://mps-v1-portal.casetify.com/",
    }

    try:
        resp = _session.get(
            ASSEMBLY_TASK_URL,
            params={"params": params_json},
            headers=_build_headers(state_store.current_token, extra_headers),
            timeout=15,
        )
        resp.raise_for_status()

        payload = resp.json()
        assembly_tasks = payload.get("assembly_task") if isinstance(payload, dict) else None
        if not isinstance(assembly_tasks, list) or not assembly_tasks:
            return None

        slots_info_list: List[Dict[str, Any]] = []
        target_keyword = "bumper"
        target_keyword_stand = "stand"

        for ass_skus in assembly_tasks:
            if not isinstance(ass_skus, dict):
                continue

            is_cancelled = ass_skus.get("cancelled", "")
            assembly_task_id = ass_skus.get("assembly_task_id", "")
            sku_items = ass_skus.get("assembly_skus", [])
            assembly_status = ass_skus.get("status", "")

            printing_batch_iid = ""
            printing_task = ass_skus.get("printing_task")
            if isinstance(printing_task, dict):
                raw_batch_iid = printing_task.get("printing_batch_iid")
                printing_batch_iid = "" if raw_batch_iid is None else str(raw_batch_iid)

            if not isinstance(sku_items, list):
                continue

            has_ring_stand = any(
                isinstance(item, dict) and target_keyword_stand in (item.get("desc") or "").lower()
                for item in sku_items
            )

            for ass_sku in sku_items:
                if not isinstance(ass_sku, dict):
                    slots_info_list.append(create_default_slot(assembly_task_id))
                    continue

                sku_desc = ass_sku.get("desc") or "无描述"
                if target_keyword not in sku_desc.lower():
                    continue

                slots_info_list.append(
                    {
                        "sku": ass_sku.get("sku_no", "无SKU编码"),
                        "status": "empty",
                        "sku_desc": sku_desc,
                        "is_cancelled": is_cancelled,
                        "is_ring_stand": has_ring_stand,
                        "assembly_task_id": assembly_task_id,
                        "printing_batch_iid": printing_batch_iid,
                        "assembly_status": assembly_status,
                    }
                )

        missing_count = 12 - len(slots_info_list)
        if missing_count > 0:
            slots_info_list.extend([create_default_slot() for _ in range(missing_count)])

        return slots_info_list

    except Exception as e:
        logger.error(f"❌ [明细获取失败] IID {iid}: {e}")
        return None
