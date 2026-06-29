import os
import json
import shutil
from datetime import date
from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    send_from_directory, jsonify
)
from db import get_conn, init_db
from pdf_gen import gerar_pdf_orcamento, OUTPUT_DIR
from email_sender import enviar_orcamento_email

BASE_DIR = os.path.dirname(__file__)
LOGO_DIR = os.path.join(BASE_DIR, "data", "logo")
os.makedirs(LOGO_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-troque-em-producao")

with app.app_context():
    init_db()


# ---------- Empresa ----------

@app.route("/empresa", methods=["GET", "POST"])
def empresa():
    conn = get_conn()
    if request.method == "POST":
        logo_file = request.files.get("logo")
        logo_path = None
        row = conn.execute("SELECT logo_path FROM empresa WHERE id=1").fetchone()
        if row:
            logo_path = row["logo_path"]
        if logo_file and logo_file.filename:
            ext = os.path.splitext(logo_file.filename)[1]
            dest = os.path.join(LOGO_DIR, "logo" + ext)
            logo_file.save(dest)
            logo_path = dest

        try:
            porta = int(request.form.get("smtp_porta") or 587)
        except ValueError:
            porta = 587

        conn.execute(
            """UPDATE empresa SET nome=?, cnpj=?, endereco=?, telefone=?, email=?, logo_path=?,
                smtp_servidor=?, smtp_porta=?, smtp_usuario=?, smtp_senha=? WHERE id=1""",
            (
                request.form.get("nome"), request.form.get("cnpj"),
                request.form.get("endereco"), request.form.get("telefone"),
                request.form.get("email"), logo_path,
                request.form.get("smtp_servidor") or "smtp.gmail.com",
                porta, request.form.get("smtp_usuario"), request.form.get("smtp_senha"),
            ),
        )
        conn.commit()
        conn.close()
        flash("Dados da empresa salvos com sucesso.", "success")
        return redirect(url_for("empresa"))

    row = conn.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    conn.close()
    return render_template("empresa.html", empresa=row)


# ---------- Clientes ----------

@app.route("/clientes", methods=["GET", "POST"])
def clientes():
    conn = get_conn()
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("Nome é obrigatório.", "error")
        else:
            cid = request.form.get("id")
            dados = (
                nome, request.form.get("documento"), request.form.get("endereco"),
                request.form.get("telefone"), request.form.get("email"),
            )
            if cid:
                conn.execute(
                    "UPDATE clientes SET nome=?, documento=?, endereco=?, telefone=?, email=? WHERE id=?",
                    dados + (cid,),
                )
            else:
                conn.execute(
                    "INSERT INTO clientes (nome, documento, endereco, telefone, email) VALUES (?, ?, ?, ?, ?)",
                    dados,
                )
            conn.commit()
            flash("Cliente salvo com sucesso.", "success")
        conn.close()
        return redirect(url_for("clientes"))

    rows = conn.execute("SELECT * FROM clientes ORDER BY nome").fetchall()
    conn.close()
    return render_template("clientes.html", clientes=rows)


@app.route("/clientes/<int:cid>/excluir", methods=["POST"])
def excluir_cliente(cid):
    conn = get_conn()
    conn.execute("DELETE FROM clientes WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    flash("Cliente excluído.", "success")
    return redirect(url_for("clientes"))


# ---------- Catálogo genérico (produtos / mão de obra) ----------

CATALOGO_CONFIG = {
    "produtos": {"campo_valor": "preco_unitario", "titulo": "Produtos", "label_valor": "Preço Unitário", "unidade": "un"},
    "mao_de_obra": {"campo_valor": "valor_unitario", "titulo": "Mão de Obra", "label_valor": "Valor por Hora", "unidade": "h"},
}


@app.route("/<tabela>", methods=["GET", "POST"])
def catalogo(tabela):
    if tabela not in CATALOGO_CONFIG:
        return "Não encontrado", 404
    cfg = CATALOGO_CONFIG[tabela]
    campo_valor = cfg["campo_valor"]
    conn = get_conn()
    if request.method == "POST":
        desc = request.form.get("descricao", "").strip()
        valor_str = (request.form.get("valor") or "0").replace(",", ".")
        try:
            valor = float(valor_str)
        except ValueError:
            valor = 0.0
        if not desc:
            flash("Descrição é obrigatória.", "error")
        else:
            item_id = request.form.get("id")
            unidade = request.form.get("unidade") or cfg["unidade"]
            if item_id:
                conn.execute(
                    f"UPDATE {tabela} SET descricao=?, unidade=?, {campo_valor}=? WHERE id=?",
                    (desc, unidade, valor, item_id),
                )
            else:
                conn.execute(
                    f"INSERT INTO {tabela} (descricao, unidade, {campo_valor}) VALUES (?, ?, ?)",
                    (desc, unidade, valor),
                )
            conn.commit()
            flash("Item salvo com sucesso.", "success")
        conn.close()
        return redirect(url_for("catalogo", tabela=tabela))

    rows = conn.execute(f"SELECT * FROM {tabela} ORDER BY descricao").fetchall()
    conn.close()
    return render_template("catalogo.html", itens=rows, tabela=tabela, cfg=cfg)


@app.route("/<tabela>/<int:item_id>/excluir", methods=["POST"])
def excluir_catalogo(tabela, item_id):
    if tabela not in CATALOGO_CONFIG:
        return "Não encontrado", 404
    conn = get_conn()
    conn.execute(f"DELETE FROM {tabela} WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    flash("Item excluído.", "success")
    return redirect(url_for("catalogo", tabela=tabela))


# ---------- Orçamento ----------

@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("novo_orcamento"))


@app.route("/orcamento/novo", methods=["GET"])
def novo_orcamento():
    conn = get_conn()
    clientes_rows = conn.execute("SELECT * FROM clientes ORDER BY nome").fetchall()
    produtos_rows = conn.execute("SELECT * FROM produtos ORDER BY descricao").fetchall()
    mo_rows = conn.execute("SELECT * FROM mao_de_obra ORDER BY descricao").fetchall()
    conn.close()

    clientes_json = [dict(r) for r in clientes_rows]
    catalogo_json = {
        "produto": [
            {"id": r["id"], "descricao": r["descricao"], "unidade": r["unidade"], "valor": r["preco_unitario"]}
            for r in produtos_rows
        ],
        "mao_de_obra": [
            {"id": r["id"], "descricao": r["descricao"], "unidade": r["unidade"], "valor": r["valor_unitario"]}
            for r in mo_rows
        ],
    }
    return render_template(
        "orcamento.html",
        clientes=clientes_rows,
        clientes_json=json.dumps(clientes_json),
        catalogo_json=json.dumps(catalogo_json),
    )


@app.route("/orcamento", methods=["POST"])
def criar_orcamento():
    cliente_id = request.form.get("cliente_id")
    validade = request.form.get("validade_dias") or 15
    observacoes = request.form.get("observacoes") or ""
    itens_json = request.form.get("itens_json") or "[]"

    try:
        itens = json.loads(itens_json)
    except json.JSONDecodeError:
        itens = []

    if not cliente_id or not itens:
        flash("Selecione um cliente e adicione ao menos um item.", "error")
        return redirect(url_for("novo_orcamento"))

    total = sum(float(i["valor_total"]) for i in itens)

    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO orcamentos (cliente_id, data, validade_dias, observacoes, total) VALUES (?, ?, ?, ?, ?)",
        (cliente_id, date.today().isoformat(), int(validade), observacoes, total),
    )
    orcamento_id = cur.lastrowid
    for item in itens:
        conn.execute(
            """INSERT INTO orcamento_itens
               (orcamento_id, tipo, descricao, unidade, quantidade, valor_unitario, valor_total)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (orcamento_id, item["tipo"], item["descricao"], item.get("unidade", ""),
             float(item["quantidade"]), float(item["valor_unitario"]), float(item["valor_total"])),
        )
    conn.commit()

    empresa = conn.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    cliente = conn.execute("SELECT * FROM clientes WHERE id=?", (cliente_id,)).fetchone()
    orcamento = conn.execute("SELECT * FROM orcamentos WHERE id=?", (orcamento_id,)).fetchone()
    itens_db = conn.execute("SELECT * FROM orcamento_itens WHERE orcamento_id=?", (orcamento_id,)).fetchall()
    conn.close()

    gerar_pdf_orcamento(empresa, cliente, orcamento, itens_db)

    return redirect(url_for("ver_orcamento", orcamento_id=orcamento_id))


@app.route("/orcamento/<int:orcamento_id>")
def ver_orcamento(orcamento_id):
    conn = get_conn()
    orcamento = conn.execute("SELECT * FROM orcamentos WHERE id=?", (orcamento_id,)).fetchone()
    cliente = conn.execute("SELECT * FROM clientes WHERE id=?", (orcamento["cliente_id"],)).fetchone()
    itens = conn.execute("SELECT * FROM orcamento_itens WHERE orcamento_id=?", (orcamento_id,)).fetchall()
    conn.close()
    if not orcamento:
        return "Não encontrado", 404
    return render_template("orcamento_detalhe.html", orcamento=orcamento, cliente=cliente, itens=itens)


@app.route("/orcamento/<int:orcamento_id>/pdf")
def download_pdf(orcamento_id):
    filename = f"orcamento_{orcamento_id:04d}.pdf"
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=False)


@app.route("/orcamento/<int:orcamento_id>/enviar-email", methods=["POST"])
def enviar_email(orcamento_id):
    destinatario = request.form.get("destinatario", "").strip()
    if not destinatario:
        flash("Informe o email do destinatário.", "error")
        return redirect(url_for("ver_orcamento", orcamento_id=orcamento_id))

    conn = get_conn()
    empresa = conn.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    conn.close()

    filename = f"orcamento_{orcamento_id:04d}.pdf"
    pdf_path = os.path.join(OUTPUT_DIR, filename)

    try:
        enviar_orcamento_email(
            empresa, destinatario, f"Orçamento #{orcamento_id}",
            "Olá, segue em anexo o orçamento solicitado.", pdf_path,
        )
        flash("Email enviado com sucesso.", "success")
    except Exception as e:
        flash(f"Erro ao enviar email: {e}", "error")

    return redirect(url_for("ver_orcamento", orcamento_id=orcamento_id))


# ---------- PWA ----------

@app.route("/manifest.json")
def manifest():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "manifest.json")


@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "service-worker.js")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
