# 内存状态集中管理 (Token, PB, 硬件绑定)
import logging
from typing import Dict, Optional
from ..config import AVAILABLE_BOARDS
from ..utils.serial_hardware import send_hardware_command

class StateStore:
    def __init__(self):
        self.current_token: Optional[str] = None
        self.active_pb_list: Dict[str, dict] = {}
        self.board_mapping: Dict[str, int] = {}

    def assign_board(self, pb_id: str) -> Optional[int]:
        """为扫入的 PB 动态分配空闲的物理灯板地址"""
        if pb_id in self.board_mapping:
            return self.board_mapping[pb_id]
            
        used_addrs = list(self.board_mapping.values())
        for addr in AVAILABLE_BOARDS:
            if addr not in used_addrs:
                self.board_mapping[pb_id] = addr
                logging.info(f"🔗 [硬件绑定] 业务 PB [{pb_id}]数据正常,已挂载至物理灯板地址: #{addr}")
                return addr
        logging.warning(f"⚠️ [硬件耗尽] 物理灯板不够用！无法为 {pb_id} 分配灯板")
        return None

    def release_board(self, pb_id: str) -> Optional[int]:
        """释放 PB 绑定的硬件"""
        print(self.board_mapping.get(pb_id))
        if pb_id in self.board_mapping:
            board_addr = self.board_mapping.pop(pb_id)
            pb_data = state_store.active_pb_list.pop(pb_id)
            print("pop:",board_addr)
            if board_addr is not None:
            	send_hardware_command(board_addr=board_addr, slot_index=0xFF, action_code=0x00)
            logging.info(f"🔓 [硬件解绑] 物理灯板地址 #{board_addr} && {pb_data.get('pb_id')}已成功释放")
            return board_addr
        return None

# 单例全局状态，供各服务与路由共享
state_store = StateStore()