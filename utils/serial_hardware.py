# 串口通讯与协议解析
import logging
import serial
from typing import Optional
from ..config import SERIAL_CFG

ser: Optional[serial.Serial] = None

if SERIAL_CFG.get("enabled", False):
    try:
        ser = serial.Serial(
            port=SERIAL_CFG.get("port", "COM3"),
            baudrate=SERIAL_CFG.get("baud_rate", 9600),
            timeout=SERIAL_CFG.get("timeout", 1)
        )
        logging.info(f"🔌 [串口成功] 已打开串口设备: {SERIAL_CFG.get('port')}")
    except Exception as e:
        logging.error(f"❌ [串口失败] 无法打开串口 {SERIAL_CFG.get('port')}: {e}，切入模拟模式")
else:
    logging.info("💡 [串口提示] 配置为纯软件模式，未启用物理串口")

def send_hardware_command(board_addr: int, slot_index: int, action_code: int):
    """
    符合《通信协议标准 V1.0》的串口命令发送函数
    :param board_addr:  物理板子地址 (1-8)
    :param slot_index:  0-11 号格子，0xFF 代表整板广播
    :param action_code: 0x00=灭灯, 0x01=常亮黄, 0x02=闪烁黄(强高亮), 0x03=淡蓝, 0x04=红灯报警
    """
    if ser and ser.is_open:
        try:
            cmd = bytearray([0x55, board_addr & 0xFF, slot_index & 0xFF, action_code & 0xFF, 0xAA])
            ser.write(cmd)
            logging.info(f"🔌 [串口指令] 板卡 #{board_addr} | 格子 #{slot_index} | 动作: {hex(action_code)} -> HEX: {cmd.hex().upper()}")
        except Exception as e:
            logging.error(f"❌ [串口发送异常]: {e}")
    else:
        logging.info(f"🤖 [模拟硬件] 板卡 #{board_addr} | 格子 #{slot_index} | 执行动作代码: {hex(action_code)}")