# 上游云端 API 交互
import logging
import requests
import json
from urllib.parse import urlencode
from typing import Optional, List, Dict, Any
from ..config import API_BASE_URL,ASSEMBLY_TASK_URL,API_HISTORY_URL
from .state_store import state_store

def fetch_internal_id_from_cloud(pb_number: str) -> Optional[str]:
    """从上游系统搜索并获取 PB 的内部唯一 IID"""

    url = f"{API_BASE_URL}?params={{\"printing_station\":\"7Za3X5Qgtbv7PvFk\",\"search_batch_no\":\"%{pb_number}%\",\"offset\":0,\"limit\":20}}"
    headers = {
        "Authorization": f"{state_store.current_token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Content-Type": "application/json"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data_list = resp.json().get("printing_batch", {}).get("data", [])
        if data_list:
            return data_list[0].get("iid")
    except Exception as e:
        logging.error(f"❌ [IID 获取失败] PB {pb_number}: {e}")
    return None
# def fetch_printing_id_from_barcode_cloud(bucket: str) ->Optional[str]:
#     params_dict = {
#         "barcode": bucket,
#         "limit": 1,
#         "offset": 0
#     }
#     headers = {
#         "Authorization": f"{state_store.current_token}",
#         "Content-Type": "application/json",
#         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
#     }
#     try:
#         resp = requests.get(
#             API_BASE_URL, 
#             params={"params": json.dumps(params_dict,separators=(',', ':'))},
#             headers=headers, timeout=10
#         )
#         resp.raise_for_status()
#         task_node = resp.json()
#         if not task_node:
#             return None
#         return task_node.get("data",[])[0].get("iid",'')

#     except Exception as e:
#         logging.error(f"❌ [装配排版信息获取失败]  {bucket}: {e}")
    # return None


def fetch_printing_id_from_barcode_cloud(bucket: str) -> Optional[str]:
    # 1. 构造 JSON 字符串（紧凑模式，剔除空格）
    compact_json = json.dumps(
        {
            "barcode": bucket,
            "limit": 1,
            "offset": 0
        }, 
        separators=(',', ':')
    )
    
    # 2. GET 请求移除不必要的 Content-Type
    headers = {
        "Authorization": f"{state_store.current_token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    
    try:
        resp = requests.get(
            API_BASE_URL, 
            params={"params": compact_json},
            headers=headers, 
            timeout=10
        )
        resp.raise_for_status()
        
        task_node = resp.json()
        if not task_node or not isinstance(task_node, dict):
            return None
        data_list = task_node.get('printing_batch',{})
        first_item = data_list.get('data',[])[0].get('iid','')
        return first_item

    except Exception as e:
        logging.error(f"❌ [装配排版信息获取失败] {bucket}: {e}")
        return None




def fetch_slots_info_from_cloud(iid: str) -> Optional[List[Dict[str, Any]]]:
    """根据 IID 拉取 12 个格子的明细数据"""
    url = f"{API_BASE_URL}/{iid}"
    headers = {
        "Authorization": f"{state_store.current_token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        
        batch_node = resp.json().get("printing_batch", {})
        if not batch_node or not isinstance(batch_node, dict):
            return None
            
        batch_no = batch_node.get("batch_no", "")
        station_name = batch_node.get("printing_station", {}).get("display_name", "未知工位") if isinstance(batch_node.get("printing_station"), dict) else "未知工位"
        
        slots = batch_node.get("slots", [])
        slots_info_list: List[Dict[str, Any]] = []
        rejected_reason = ''
        slot_limit = 12
        slot_mark = 1
        printing_task_id = ''
        for slot in slots:
            if slot_mark > slot_limit:
                break
            if not isinstance(slot, dict):
                # 遇到异常元素，追加默认空位
                slots_info_list.append(create_default_printing_slot(batch_no,station_name))
                continue
            item = slot.get("printing_task",'')
            assembly_task = slot.get("assembly_task")
            sales_order = slot.get("sales_order")
            #获取物品iid 及历史状态

            if item:
                printing_task_id = item.get('iid','')
            if printing_task_id :
                rejected_reason = fetch_npp(iid,printing_task_id)

            # 1. 安全提取 assembly_task_id 与 status
            if isinstance(assembly_task, dict):
                assembly_task_id = assembly_task.get("assembly_task_id", "Non_task")
                sku_status = "empty"
            else:
                assembly_task_id = "Non_task"
                sku_status = "block"

            # 2. 安全提取 cancelled 状态（解决 UnboundLocalError 核心）
            cancelled = False
            if isinstance(sales_order, dict):
                # 提取 cancelled 状态并统一规范为 bool 或 标准格式
                raw_cancelled = sales_order.get("cancelled", False)
                cancelled = raw_cancelled is True or str(raw_cancelled).lower() == "true"

            # 3. 构造与全局 Schema 对齐的字典结构
            slots_info_list.append({
                "sku": "空位" if sku_status == "block" else "待确定",
                "status": sku_status,
                "sku_desc": "无描述",
                "is_ring_stand": False,
                "assembly_task_id": assembly_task_id,
                "cancelled": cancelled,
                "batch_no": batch_no,
                "station": station_name,
                "rejected_reason": rejected_reason
            })
            rejected_reason = ''
            slot_mark +=1
        
        return slots_info_list

    except Exception as e:
        logging.error(f"❌ [明细获取失败] IID {iid}: {e}")
        return None

def create_default_printing_slot(batch_no: str = "",station_name:str = "Non_station") -> Dict[str, Any]:
    return {
        "sku": "空位",
        "status": "block",
        "sku_desc": "无描述",
        "is_ring_stand": False,
        "assembly_task_id": "Non_task",
        "cancelled": False,
        "batch_no": batch_no,
        "station": station_name,
        "rejected_reason": ''
    }

def create_default_slot(task_id: str = "Non_task") -> Dict[str, Any]:
    return {
        "sku": "空位",
        "status": "block",
        "sku_desc": "无描述",
        "is_cancelled": 'false',
        "is_ring_stand": False,
        "assembly_task_id": task_id,
        "printing_batch_iid":'',
        "assembly_status":''
    }
# assembly_task[0].printing_task.printing_batch_iid
# assembly_task[2].status
def fetch_accembly_slots_info_from_cloud(iid: str) -> Optional[List[Dict[str, Any]]]:

    # 1. Define params as a standard Python dict
    params_dict = {
        "status": json.dumps(["Pending to Assemble", "Rejected", "Completed"]),
        "confirm_cancelled": False,
        "search_for_bucket": f"%{iid}%"
    }

    # 2. Safely encode into a query string
    query_string = urlencode({"params": json.dumps(params_dict)})

    # 3. Construct the final URL
    # url = f"{ASSEMBLY_TASK_URL}?{query_string}"
    url = f'{ASSEMBLY_TASK_URL}?params={{"status":[\"Pending to Assemble\",\"Rejected\",\"Completed\"],"confirm_cancelled":false,"search_for_bucket":"%{iid}%"}}'
    headers = {
        "Authorization": f"{state_store.current_token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "access-control-allow-origin":"https://mps-v1-portal.casetify.com",
        "referer":"https://mps-v1-portal.casetify.com/"
    }
    # 统一定义默认空槽位的生成函数，保证字段结构一致

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        
        assembly_tasks = resp.json().get("assembly_task", [])
        if not assembly_tasks:
            return None

        slots_info_list: List[Dict[str, Any]] = []
        target_keyword = "bumper"
        target_keyword_stand = "stand"
        printing_batch_iid = ''
        assembly_status = ''
        # 3. 遍历解析槽位数据
        for ass_skus in assembly_tasks:
            if not isinstance(ass_skus, dict):
                continue
            is_cancelled = ass_skus.get('cancelled','')
            assembly_task_id = ass_skus.get('assembly_task_id', '')
            sku_items = ass_skus.get('assembly_skus', [])
            assembly_status = ass_skus.get('status','')
            if ass_skus.get('printing_task',{}):
                printing_batch_iid = ass_skus.get('printing_task').get('printing_batch_iid')
            if not isinstance(sku_items, list):
                continue

            # --- 步骤 3.1: 提前扫描判定该任务内是否存在 stand ---
            has_ring_stand = False
            for item in sku_items:
                if isinstance(item, dict):
                    desc = (item.get("desc") or "").lower()
                    if target_keyword_stand in desc:
                        has_ring_stand = True
                        break

            # --- 步骤 3.2: 提取符合条件 (bumper) 的 SKU ---
            task_has_valid_bumper = False
            for ass_sku in sku_items:
                # 非字典对象（即无效/空数据），追加默认空位
                if not isinstance(ass_sku, dict):
                    slots_info_list.append(create_default_slot(assembly_task_id))
                    continue

                sku_desc = ass_sku.get("desc") or "无描述"
                
                # 过滤不包含 bumper 的条目
                if target_keyword not in sku_desc.lower():
                    continue

                # 命中 Bumper，添加有效数据
                slots_info_list.append({
                    "sku": ass_sku.get("sku_no", "无SKU编码"),
                    "status": "empty",
                    "sku_desc": sku_desc,
                    "is_cancelled": is_cancelled,
                    "is_ring_stand": has_ring_stand,
                    "assembly_task_id": assembly_task_id,
                    "printing_batch_iid":printing_batch_iid,
                    "assembly_status":assembly_status
                })
                task_has_valid_bumper = True

        # 4. 补齐至至少 12 个槽位 (保持数据结构规范统一)
        missing_count = 12 - len(slots_info_list)
        if missing_count > 0:
            slots_info_list.extend([create_default_slot() for _ in range(missing_count)])

        return slots_info_list

    except Exception as e:
        logging.error(f"❌ [明细获取失败] IID {iid}: {e}")
        return None

def fetch_npp(iid: str, printing_task_iid: str) -> str | None:
        if not state_store.current_token:
            logging.warning("fetch_npp failed: Authorization token is missing.")
            return None

        url = f"{API_HISTORY_URL}/{printing_task_iid}/history"
        headers = {
            # 注意：通常标准的 Bearer Token 需要加前缀，如果服务端确实只收纯 token 请保留原样
            "Authorization": f"{state_store.current_token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            # GET 请求不需要 Content-Type，建议保留 Accept
            "Accept": "application/json",
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            res_json = response.json()

            # 防御性解析：防止 response.json() 返回 None 或非 dict 类型
            if not isinstance(res_json, dict):
                return None

            printing_task = res_json.get("printing_task") or {}
            history_list = printing_task.get("history") or []

            for his in history_list:
                if isinstance(his, dict) and his.get("printing_batch_iid") == iid:
                    # 匹配到即返回，找不到会默认返回 None
                    return his.get("reason")

        except requests.exceptions.RequestException as e:
            logging.error(
                f"[printing_task_iid history Fetch Error] Request failed for "
                f"task_iid: {printing_task_iid}, batch_iid: {iid}. Error: {e}"
            )
        except Exception as e:
            logging.exception(
                f"[printing_task_iid history Fetch Error] Unexpected parsing error for "
                f"task_iid: {printing_task_iid}, batch_iid: {iid}"
            )

        return None
