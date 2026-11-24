import json
import io
from typing import List, Dict, Any
import copy


def printing_assembly_slot_sorter(assembly_tasks: list, printing_slots: list) -> list:
    finish_slots = []
    
    # 1. 统一标准的默认槽位 Schema
    default_slot_template = {
        "sku": "空位",
        "status": "block",
        "sku_desc": "无描述",
        "is_ring_stand": False,
        "assembly_task_id": "Non_task"
    }

    # 2. 建立索引映射 (O(M))：以 assembly_task_id 为 key
    # 同时使用 copy.deepcopy 避免后续修改污染入参 assembly_tasks
    task_map: Dict[Any, Dict[str, Any]] = {}
    for task in assembly_tasks:
        if isinstance(task, dict):
            task_id = task.get("assembly_task_id")
            if task_id is not None and task_id != "":
                task_map[task_id] = copy.deepcopy(task)

    # 3. 遍历 printing_slots 进行匹配 (O(N))
    for pslot in printing_slots:
        if not isinstance(pslot, dict):
            finish_slots.append(copy.deepcopy(default_slot_template))
            continue

        p_id = pslot.get('assembly_task_id')
        
        # 命中匹配项
        if p_id in task_map:
            matched_task = task_map[p_id]
            cancelled_val = matched_task["is_cancelled"]
            if pslot.get('rejected_reason') :
                cancelled_val = 'true'
            matched_task['batch_no'] = pslot.get('batch_no')
            
            # 兼容多种格式的 cancelled 状态判断 (布尔值 / 字符串 "true" / "1")
            is_cancelled = cancelled_val is True or str(cancelled_val).lower() == 'true'
            if is_cancelled:
                matched_task['status'] = 'block'
                
            finish_slots.append(matched_task)
        else:
            # 未命中匹配项，追加独立的空位模板
            finish_slots.append(copy.deepcopy(default_slot_template))

    return finish_slots

def printing_assembly_slot_sorter_legacy_fixed(assembly_tasks: list, printing_slots: list) -> list:
    finish_slots = []
    default_slot_template = {
        "sku": "空位",
        "status": "block",
        "sku_desc": "无描述",
        "station": "Non_task"
    }

    for pslot in printing_slots:
        matched = False
        p_id = pslot.get('assembly_task_id') if isinstance(pslot, dict) else None
        for a_task in assembly_tasks:
            if isinstance(a_task, dict) and a_task.get('assembly_task_id') == p_id:
                a_task['cancelled'] = pslot.get('cancelled')
                a_task['batch_no'] = pslot.get('batch_no')
                if pslot.get('cancelled') == 'true':
                	a_task['status'] = 'block'
                finish_slots.append(a_task)
                matched = True
                break  # 找到了匹配项，立即跳出内层循环
        
        # 如果内层循环结束都没有找到匹配项
        if not matched:
            finish_slots.append(copy.deepcopy(default_slot_template))

    return finish_slots


