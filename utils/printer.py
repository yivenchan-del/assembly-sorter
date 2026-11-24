# 二维码生成与打印机 DC 绘制
import logging
from datetime import datetime
from typing import Optional

try:
    import qrcode
    from PIL import Image, ImageWin, ImageDraw, ImageFont
    import win32print
    import win32ui
    HAS_PRINT_LIBS = True
except ImportError:
    HAS_PRINT_LIBS = False
    logging.warning("⚠️ [打印警告] 未检测到 win32print 或 qrcode 模块，标签打印功能将以模拟模式运行。")

def print_qr_code_safe(pb_id_value: str):
    """适配 Windows 打印机 DPI 的标准标签打印逻辑"""
    if not HAS_PRINT_LIBS:
        logging.info(f"🖨️ [模拟打印] 标签打印机未安装库，模拟打印 QR 码: {pb_id_value}")
        return

    try:
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=8, border=2)
        qr.add_data(pb_id_value)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

        printer_name = win32print.GetDefaultPrinter()
        hprinter = win32print.OpenPrinter(printer_name)
        
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)
        hdc.StartDoc(f"PB_QR_{pb_id_value}")
        hdc.StartPage()

        dib = ImageWin.Dib(img)
        dib.draw(hdc.GetHandleOutput(), (50, 50, 250, 250))

        hdc.EndPage()
        hdc.EndDoc()
        hdc.DeleteDC()
        win32print.ClosePrinter(hprinter)
        logging.info(f"🖨️ [打印成功] 已经向默认打印机 [{printer_name}] 发送 PB: {pb_id_value}")
    except Exception as e:
        logging.error(f"❌ [打印失败] 无法打印二维码: {e}")

def print_qr_code(pb_id_value: str, Uname: Optional[str], borard_addr: int):
    if not HAS_PRINT_LIBS:
        logging.info(f"🖨️ [模拟打印] 模拟生成排版排版标签: {pb_id_value}")
        return
    try:    
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(pb_id_value)
        qr.make(fit=True)

        user = Uname if Uname is not None else "李白"
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        logging.info(pb_id_value)

        text = pb_id_value
        font = ImageFont.truetype("msyh.ttc", 35)
        now = datetime.now()
        pb_sort = str(borard_addr)
        datetimestr = now.strftime("%Y年%m月%d日%H时%M分")

        draw_tmp = ImageDraw.Draw(qr_img)
        bbox = draw_tmp.textbbox((0, 0), text, font=font)
        text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]

        img_width, img_height = qr_img.size
        new_width = img_width * 3
        new_height = (img_height + text_height) * 2  
        new_img = Image.new("RGB", (new_width, new_height), "white")

        new_img.paste(qr_img, (0 , 0))

        draw = ImageDraw.Draw(new_img)
        x = (img_width - text_width) // 2
        y = img_height + 10  
        draw.text((x + 20, y), text, font=font, fill="black")
        draw.text((img_width / 2 + new_width / 3, y / 3), user, font=font, fill="black")
        draw.text((img_width / 2 + new_width / 3, y / 2 + 150), f"PB：{pb_sort}", font=font, fill="black")
        draw.text((img_width / 2 + x, y + 100), datetimestr, font=font, fill="black")

        printer_name = win32print.GetDefaultPrinter()
        logging.info(printer_name)
        hprinter = win32print.OpenPrinter(printer_name)
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)
        hdc.StartDoc("QR Code Print")
        hdc.StartPage()

        dib = ImageWin.Dib(new_img)
        dib.draw(hdc.GetHandleOutput(), (0, 0, new_img.size[0], new_img.size[1]))

        hdc.EndPage()
        hdc.EndDoc()
        hdc.DeleteDC()
        win32print.ClosePrinter(hprinter)
    except Exception as e:
        logging.error(f"❌ [打印失败] 无法打印二维码: {e}")