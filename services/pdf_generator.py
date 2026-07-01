import os
from typing import Dict, Any, Optional

from fpdf import FPDF

from utils.formatter import format_price, format_change

PDF_DIR = os.path.join("data", "pdfs")


def _ensure_pdf_dir():
    os.makedirs(PDF_DIR, exist_ok=True)


ARIAL = r"C:\Windows\Fonts\arial.ttf"
ARIAL_BD = r"C:\Windows\Fonts\arialbd.ttf"


def generate_pdf_report(scan_result: Dict[str, Any]) -> Optional[str]:
    try:
        _ensure_pdf_dir()

        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.add_font("Arial", "", ARIAL)
        pdf.add_font("Arial", "B", ARIAL_BD)
        pdf.set_auto_page_break(auto=True, margin=15)

        pdf.add_page()

        sym = scan_result.get("symbol", "N/A")
        pdf.set_font("Arial", "B", 16)
        pdf.cell(0, 10, text="Technical Report - " + sym, new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(5)

        market_display = {"SAUDI": "Saudi", "US": "US", "CRYPTO": "Crypto"}
        market = market_display.get(scan_result.get("market", ""), scan_result.get("market", ""))
        tf = scan_result.get("timeframe", "1d")
        pdf.set_font("Arial", "", 11)
        pdf.cell(0, 7, text="Market: " + market + "  |  Timeframe: " + tf, new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, text="Price: " + format_price(scan_result.get("current_price")), new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, text="Change: " + format_change(scan_result.get("change_percent")), new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, text="Trend: " + str(scan_result.get("trend", "N/A")), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, text="Technical Indicators", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Arial", "", 11)

        ind = scan_result.get("indicators", {})
        sup = scan_result.get("support")
        res = scan_result.get("resistance")

        rsi_val = ind.get("rsi")
        rsi_str = f"{rsi_val:.1f}" if isinstance(rsi_val, (int, float)) else "N/A"
        macd_str = "Positive" if (ind.get("macd_line") or 0) > (ind.get("macd_signal") or 0) else "Negative"
        atr_val = ind.get("atr")
        atr_str = f"{atr_val:.2f}" if isinstance(atr_val, (int, float)) else "N/A"

        items = [
            ("RSI (14)", rsi_str),
            ("MACD", macd_str),
            ("EMA 20", format_price(ind.get("ema_20"))),
            ("EMA 50", format_price(ind.get("ema_50"))),
            ("EMA 200", format_price(ind.get("ema_200"))),
            ("ATR", atr_str),
            ("Support", format_price(sup)),
            ("Resistance", format_price(res)),
        ]
        for label, value in items:
            pdf.cell(0, 7, text=label + ": " + value, new_x="LMARGIN", new_y="NEXT")

        pdf.ln(5)

        score = scan_result.get("score")
        if score:
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, text="Technical Score", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Arial", "", 11)
            pdf.cell(0, 7, text="Overall: " + f"{score.overall:.0f}/100", new_x="LMARGIN", new_y="NEXT")
            pdf.cell(0, 7, text="Rating: " + str(scan_result.get("rating", "N/A")), new_x="LMARGIN", new_y="NEXT")
            pdf.cell(0, 7, text="Risk: " + str(scan_result.get("risk_level", "N/A")), new_x="LMARGIN", new_y="NEXT")

        pdf.ln(5)

        summary = scan_result.get("summary", "")
        if summary:
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, text="Summary", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Arial", "", 11)
            pdf.multi_cell(0, 7, text=summary)

        pdf.ln(5)
        disc = scan_result.get("disclaimer", "")
        if disc:
            pdf.set_font("Arial", "", 8)
            pdf.multi_cell(0, 5, text=disc)

        filename = sym + "_" + tf + ".pdf"
        filename = filename.replace("/", "_").replace("\\", "_")
        filepath = os.path.join(PDF_DIR, filename)
        pdf.output(filepath)
        return filepath
    except Exception:
        return None
