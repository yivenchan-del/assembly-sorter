# API 路由定义与请求处理
import base64
import logging
import os
import time
import asyncio
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..config import BASE_DIR, IMAGE_DIR
from ..models.schemas import TokenModel, SkuMatchModel, SaveImageData,UserData
from ..services.state_store import state_store
from ..services.cloud_service import fetch_internal_id_from_cloud, fetch_slots_info_from_cloud,fetch_accembly_slots_info_from_cloud,fetch_printing_id_from_barcode_cloud
from ..utils.serial_hardware import send_hardware_command
from ..utils.printer import print_qr_code
from ..utils.printing_assembly_slot_sorter import printing_assembly_slot_sorter,printing_assembly_slot_sorter_legacy_fixed
from ..config import EXE_DIR, IMAGE_DIR, INDEX_HTML_PATH

router = APIRouter()
# 全局异步锁，防止并发扫码导致状态竞争
match_lock = asyncio.Lock()

@router.post("/update_token")
def update_token(data: TokenModel):
    if not data.token:
        raise HTTPException(status_code=400, detail="无效的 Token")
    state_store.current_token = data.token
    return {"status": "success"}

@router.get("/api/active_pbs")
async def get_active_pbs():
    """全场数据同步接口"""
    return {
        "status": "success",
        "active_pbs": state_store.active_pb_list
    }

@router.get("/api/pb/{pb_id}")
async def get_pb_info(pb_id: str):
    """扫描 PB 码：抓取数据、分配硬件并存入后台集中控制"""
    if not state_store.current_token:
        raise HTTPException(status_code=401, detail="请先同步！")

    if pb_id in state_store.active_pb_list:
        return state_store.active_pb_list[pb_id]

    logging.info(f"正在向云端查询 PB: {pb_id}")
    iid = ''
    iid = fetch_printing_id_from_barcode_cloud(pb_id)
    #装配排版数据乱序
    assembly_tasks = fetch_accembly_slots_info_from_cloud(pb_id)
    #印刷排版数据
    
    slots_data = []
    if not iid:
        for valid_iid in assembly_tasks:
            assembly_status = valid_iid.get('assembly_status','')
            id  = valid_iid.get('printing_batch_iid','')
            if id is True:
                iid = id
            if assembly_status == 'Pending to Assemble' and iid:
                logging.info(f'Pending to Assemble iid:{iid}')
                break
    slots_data = fetch_slots_info_from_cloud(iid)
    if not iid:
        state_store.release_board(pb_id)
        raise HTTPException(status_code=404, detail=f"未找到该 PB [{pb_id}] 的内部 IID")
    # print('assembly_tasks',assembly_tasks)
    print('slots_data',slots_data)

    fnish_slots = printing_assembly_slot_sorter(assembly_tasks,slots_data)
    if not fnish_slots:
        state_store.release_board(pb_id)
        raise HTTPException(status_code=404, detail=f"未找到该 PB [{pb_id}] 的槽位排版数据,请检查此盘是否已全部取消订单")
    #绑定pb和灯板
    board_addr = state_store.assign_board(pb_id)

    if not board_addr:
        raise HTTPException(status_code=400, detail="物理灯板已用满，请先完成现有的排版任务！")
        
    state_store.active_pb_list[pb_id] = {
        "pb_id": pb_id,
        "board_addr": board_addr,
        "iid": iid,
        "slots": fnish_slots
    }
    
    return state_store.active_pb_list[pb_id]



@router.post("/api/match_sku")
async def match_sku(data: SkuMatchModel):
    """单点强高亮匹配接口（含锁与状态指针优化）"""
    sku = data.sku
    
    # ⚡ 1. 引入异步锁，保证线程/协程安全
    async with match_lock:
        active_pbs = state_store.active_pb_list
        target_p_id = None
        target_s_idx = None

        # 2. 顺序遍历寻找第一个符合条件的 empty 格子
        for p_id, pb_info in active_pbs.items():
            for s_idx, slot in enumerate(pb_info.get("slots", [])):
                if slot["sku"] == sku and slot["status"] == 'empty':
                    target_p_id = p_id
                    target_s_idx = s_idx
                    break
            if target_p_id is not None:
                break

        # 全场未找到匹配的空额
        if target_p_id is None:
            return {
                "status": "not_found",
                "message": f"全场所有 PB 中，未找到需要物料 [{sku}] 的空闲格子",
                "full_data": active_pbs
            }

        # ⚡ 3. 精准复位：利用状态指针，直接复位上一个 active 的格子，避免全网格扫描
        last_active = getattr(state_store, "current_active_slot", None)
        if last_active:
            last_p_id, last_s_idx = last_active["p_id"], last_active["s_idx"]
            
            # 只有当上一个 active 格子确实存在且状态还是 active 时才复位
            if last_p_id in active_pbs and last_s_idx < len(active_pbs[last_p_id]["slots"]):
                old_slot = active_pbs[last_p_id]["slots"][last_s_idx]
                if old_slot["status"] == 'active':
                    old_slot["status"] = 'scanned'
                    old_board_addr = active_pbs[last_p_id]["board_addr"]
                    # 异步非阻塞发送串口灭灯指令
                    await asyncio.to_thread(
                        send_hardware_command, 
                        board_addr=old_board_addr, 
                        slot_index=last_s_idx, 
                        action_code=0x00
                    )

        # ⚡ 4. 激活新格子并更新状态指针
        target_pb = active_pbs[target_p_id]
        target_slot = target_pb["slots"][target_s_idx]
        target_board_addr = target_pb["board_addr"]

        target_slot["status"] = 'active'
        # 记录当前点亮的格子指针
        state_store.current_active_slot = {
            "p_id": target_p_id, 
            "s_idx": target_s_idx
        }

        logging.info(f"🎯 [精准匹配] SKU [{sku}] -> 命中 PB [{target_p_id}] (板卡 #{target_board_addr}) 的 #{target_s_idx} 号格子")
        time.sleep(0.1)
        # 异步非阻塞发送串口亮灯指令 (action_code=0x01)
        await asyncio.to_thread(
            send_hardware_command, 
            board_addr=target_board_addr, 
            slot_index=target_s_idx, 
            action_code=0x01
        )

        return {
            "status": "matched",
            "target_pb": target_p_id,
            "target_slot": target_s_idx,
            "full_data": active_pbs
        }
# @router.post("/api/match_sku")
# async def match_sku(data: SkuMatchModel):
#     """单点强高亮匹配接口"""
#     sku = data.sku
#     pb_ids = list(state_store.active_pb_list.keys())

#     target_p_id = None
#     target_s_idx = None
    
#     for p_id in pb_ids:
#         slots = state_store.active_pb_list[p_id]["slots"]
#         for s_idx, slot in enumerate(slots):
#             if slot["sku"] == sku and slot["status"] == 'empty':
#                 target_p_id = p_id
#                 target_s_idx = s_idx
#                 break
#         if target_p_id:
#             break

#     if not target_p_id:
#         return {
#             "status": "not_found",
#             "message": f"全场所有 PB 中，未找到需要物料 [{sku}] 的空闲格子",
#             "full_data": state_store.active_pb_list
#         }

#     for p_id in pb_ids:
#         board_addr = state_store.active_pb_list[p_id]["board_addr"]
#         for s_idx, slot in enumerate(state_store.active_pb_list[p_id]["slots"]):
#             if p_id == target_p_id and s_idx == target_s_idx:
#                 slot["status"] = 'active'
#                 logging.info(f"🎯 [精准匹配] SKU [{sku}] -> 命中 PB [{p_id}] (板卡 #{board_addr}) 的 #{s_idx} 号格子")
#                 send_hardware_command(board_addr=board_addr, slot_index=s_idx, action_code=0x01)
#             elif slot["status"] == 'active':
#                 slot["status"] = 'scanned'
#                 send_hardware_command(board_addr=board_addr, slot_index=s_idx, action_code=0x00)

#     return {
#         "status": "matched",
#         "target_pb": target_p_id,
#         "target_slot": target_s_idx,
#         "full_data": state_store.active_pb_list
#     }

@router.post("/api/save_png")
async def save_screenshot_and_finish(data: SaveImageData):
    """排版完成：保存截图、释放物理灯板、打印标签并移出激活列表"""
    pb_id = data.pb_id
    uname = data.name
    try:
        if "," in data.image_base64:
            _, encoded = data.image_base64.split(",", 1)
        else:
            encoded = data.image_base64

        image_bytes = base64.b64decode(encoded)
        file_path = os.path.join(IMAGE_DIR, f"{pb_id}.png")
        with open(file_path, "wb") as f:
            f.write(image_bytes)
        logging.info(f"💾 [截图保存] PB [{pb_id}] 截图成功存入 {file_path}")
        # boraddr = state_store.board_mapping.get(pb_id)
        boraddr = state_store.release_board(pb_id)
        
        # if boraddr is not None:
        #     for i in range(0x00, 0x0C):
        #         print(f"0x{i:02X}")
        #         time.sleep(0.1)
        #         send_hardware_command(board_addr=boraddr, slot_index=i, action_code=0x00)

        # if pb_id in state_store.active_pb_list:
        #     state_store.active_pb_list.pop(pb_id)
        if boraddr is not None:
            print_qr_code(pb_id, uname, boraddr)

        return {"status": "success", "file_path": file_path, "active_pbs": state_store.active_pb_list}
    except Exception as e:
        logging.error(f"❌ 保存/完成 PB [{pb_id}] 失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存或提交失败: {str(e)}")

@router.post("/api/complete_eligible_batches")
async def complete_eligible_batches(data: UserData):
    """一键完成所有符合条件的 PB 卡片（即：完全没有 empty 格子的 PB）"""
    name = data.name
    async with match_lock:
        active_pbs = state_store.active_pb_list
        if not active_pbs:
            return {
                "status": "warning",
                "message": "当前没有正在排版的 PB 卡片",
                "completed_pbs": [],
                "skipped_pbs": [],
                "full_data": active_pbs
            }

        completed_pbs = []  # 记录成功结算的 PB ID
        skipped_pbs = []    # 记录未填满、被跳过的 PB ID

        # 获取需要迭代的 PB ID 列表副本（防止遍历过程中修改字典报错）
        pb_ids = list(active_pbs.keys())

        for p_id in pb_ids:
            pb_info = active_pbs[p_id]
            slots = pb_info.get("slots", [])
            board_addr = pb_info.get("board_addr")

            # ⚡ 核心判断：检查该 PB 是否还有 empty（未填充物料）的格子
            has_empty_slot = any(slot.get("status") == "empty" for slot in slots)

            if has_empty_slot:
                # 存在空格子，不满足提交条件，跳过
                skipped_pbs.append(p_id)
                logging.info(f"⏳ [跳过结算] PB [{p_id}] 仍有未填充的空槽位，不予自动提交")
                continue

            # ----------------------------------------------------
            # 满足提交条件：全槽位无 empty（仅 scanned / active / block）
            # ----------------------------------------------------
            for s_idx, slot in enumerate(slots):
                # 如果存在残留的 active 状态，复位为 scanned 并向串口下发指令
                if slot.get("status") == "active":
                    slot["status"] = "scanned"
                    if board_addr is not None:
                        await asyncio.to_thread(
                            send_hardware_command,
                            board_addr=board_addr,
                            slot_index=s_idx,
                            action_code=0x00  # 熄灭强高亮
                        )

            # 如果当前全场强高亮指针正好在这个被结算的 PB 上，重置指针
            if state_store.current_active_slot and state_store.current_active_slot.get("p_id") == p_id:
                state_store.current_active_slot = None

            # 记录完成的 PB 并从活跃列表中移除/结算
            completed_pbs.append(p_id)
            # 💡 假设这里调用你的结算/归档逻辑：
            # await archive_and_release_pb(p_id)
            board_addr = state_store.release_board(p_id)
            if board_addr is not None:
                print_qr_code(p_id, name, board_addr)
                state_store.release_board(p_id)
            # time.sleep(0.2)
            logging.info(f"🎉 [一键完成] PB [{p_id}] 已满足全填满条件，完成自动排版并释放灯板 #{board_addr}")

        # 构建提示信息
        if not completed_pbs:
            msg = f"未结算任何 PB。当前 {len(skipped_pbs)} 个 PB 均含有空闲槽位！"
            status = "warning"
        else:
            msg = f"成功结算 {len(completed_pbs)} 个完全填满的 PB！"
            if skipped_pbs:
                msg += f"（另有 {len(skipped_pbs)} 个含空格子的 PB 已保留）"
            status = "success"

        return {
            "status": status,
            "message": msg,
            "completed_pbs": completed_pbs,
            "skipped_pbs": skipped_pbs,
            "full_data": active_pbs,
            "active_pbs": state_store.active_pb_list
        }



@router.post("/api/reset_all")
async def reset_all():
    """紧急/重置接口：一键熄灭所有物理灯，清空后台全局缓存"""
    for pb_id in list(state_store.active_pb_list.keys()):
        state_store.release_board(pb_id)
    state_store.active_pb_list.clear()
    state_store.board_mapping.clear()
    logging.info("🧹 [系统重置] 全场数据已重置，物理灯板已全部全灭清空")
    return {"status": "success"}

#点亮 1 号灯板所有灯	55 01 FF 01 AA

@router.get("/api/reset_pb/{pb_id}")
async def reset_pb(pb_id: str):
    """紧急/重置单盘接口"""
    board_addr = state_store.release_board(pb_id)
    if board_addr == None:
    	logging.error(f"🧹 [重置单盘]{pb_id} 数据重置失败!")
    logging.info(f"🧹 [重置单盘]{pb_id} 数据已重置，物理灯板{board_addr}已全部全灭清空")
    return {"status": "success", "active_pbs": state_store.active_pb_list}

@router.get("/", response_class=HTMLResponse)
def get_dashboard_page():
    if not os.path.exists(INDEX_HTML_PATH):
        return f"<h3>index.html 页面文件未找到。<br>当前检测路径: {INDEX_HTML_PATH}</h3>"
    with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
        return f.read()