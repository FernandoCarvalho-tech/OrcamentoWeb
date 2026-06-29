import os
import io
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data", "orcamentos_pdf")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def gerar_pdf_orcamento(empresa, cliente, orcamento, itens):
    """
    empresa: sqlite3.Row da tabela empresa
    cliente: sqlite3.Row da tabela clientes
    orcamento: sqlite3.Row da tabela orcamentos
    itens: lista de sqlite3.Row da tabela orcamento_itens
    """
    filename = f"orcamento_{orcamento['id']:04d}.pdf"
    filepath = os.path.join(OUTPUT_DIR, filename)

    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        topMargin=20 * mm, bottomMargin=20 * mm,
        leftMargin=18 * mm, rightMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Heading1"], fontSize=16, spaceAfter=4)
    normal = styles["Normal"]
    right = ParagraphStyle("right", parent=normal, alignment=TA_RIGHT)
    center = ParagraphStyle("center", parent=normal, alignment=TA_CENTER)

    elements = []

    logo_data = empresa["logo_data"] if empresa and empresa["logo_data"] else None
    header_cells = []
    if logo_data:
        try:
            img = Image(io.BytesIO(bytes(logo_data)), width=35 * mm, height=35 * mm)
            header_cells.append(img)
        except Exception:
            pass

    empresa_info = (
        f"<b>{empresa['nome'] or ''}</b><br/>"
        f"CNPJ: {empresa['cnpj'] or ''}<br/>"
        f"{empresa['endereco'] or ''}<br/>"
        f"Tel: {empresa['telefone'] or ''}  Email: {empresa['email'] or ''}"
    )
    header_cells.append(Paragraph(empresa_info, normal))

    if len(header_cells) == 2:
        header_table = Table([header_cells], colWidths=[40 * mm, None])
    else:
        header_table = Table([[header_cells[0]]])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 8 * mm))

    elements.append(Paragraph(f"ORÇAMENTO Nº {orcamento['id']:04d}", title_style))
    data_fmt = orcamento["data"]
    try:
        data_fmt = datetime.strptime(orcamento["data"], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        pass
    elements.append(Paragraph(f"Data: {data_fmt}  |  Validade: {orcamento['validade_dias']} dias", normal))
    elements.append(Spacer(1, 4 * mm))

    cliente_info = (
        f"<b>Cliente:</b> {cliente['nome'] or ''}<br/>"
        f"Documento: {cliente['documento'] or ''}<br/>"
        f"Endereço: {cliente['endereco'] or ''}<br/>"
        f"Tel: {cliente['telefone'] or ''}  Email: {cliente['email'] or ''}"
    )
    elements.append(Paragraph(cliente_info, normal))
    elements.append(Spacer(1, 6 * mm))

    table_data = [["Tipo", "Descrição", "Un.", "Qtd.", "Valor Unit.", "Valor Total"]]
    tipo_label = {"produto": "Produto", "mao_de_obra": "Mão de obra"}
    for item in itens:
        table_data.append([
            tipo_label.get(item["tipo"], item["tipo"]),
            item["descricao"],
            item["unidade"] or "",
            f"{item['quantidade']:.2f}",
            f"R$ {item['valor_unitario']:.2f}",
            f"R$ {item['valor_total']:.2f}",
        ])

    items_table = Table(table_data, colWidths=[25 * mm, 65 * mm, 15 * mm, 20 * mm, 25 * mm, 25 * mm], repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 6 * mm))

    total_table = Table([["TOTAL", f"R$ {orcamento['total']:.2f}"]], colWidths=[155 * mm, 25 * mm])
    total_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("LINEABOVE", (0, 0), (-1, 0), 1, colors.black),
    ]))
    elements.append(total_table)

    if orcamento["observacoes"]:
        elements.append(Spacer(1, 6 * mm))
        elements.append(Paragraph(f"<b>Observações:</b><br/>{orcamento['observacoes']}", normal))

    doc.build(elements)
    return filepath
