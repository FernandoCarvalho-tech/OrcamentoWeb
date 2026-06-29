import os
import json
import psycopg2
from datetime import date
from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    send_from_directory, jsonify, session
)
from werkzeug.security import check_password_hash, generate_password_hash
from db import get_conn, init_db
from pdf_gen import gerar_pdf_orcamento, OUTPUT_DIR
from email_sender import enviar_orcamento_email

BASE_DIR = os.path.dirname(__file__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-troque-em-producao")

with app.app_context():
    init_db()


@app.before_request
def exigir_login():
    rotas_publicas = {"login", "static", "manifest", "service_worker"}
    if request.endpoint in rotas_publicas or request.endpoint is None:
        return
    if not session.get("logado"):
        return redirect(url_for("login", next=request.path))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")
        conn = get_conn()
        row = conn.execute("SELECT * FROM login_config WHERE id=1").fetchone()
        conn.close()
        if row and usuario == row["usuario"] and check_password_hash(row["senha_hash"], senha):
            session["logado"] = True
            session["usuario"] = usuario
            destino = request.args.get("next") or url_for("novo_orcamento")
            return redirect(destino)
        flash("Usuário ou senha inválidos.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/conta", methods=["GET", "POST"])
def conta():
    conn = get_conn()
    if request.method == "POST":
        novo_usuario = request.form.get("usuario", "").strip()
        senha_atual = request.form.get("senha_atual", "")
        nova_senha = request.form.get("nova_senha", "")
        row = conn.execute("SELECT * FROM login_config WHERE id=1").fetchone()
        if not check_password_hash(row["senha_hash"], senha_atual):
            flash("Senha atual incorreta.", "error")
        elif not novo_usuario or not nova_senha:
            flash("Preencha usuário e nova senha.", "error")
        else:
            conn.execute(
                "UPDATE login_config SET usuario=?, senha_hash=? WHERE id=1",
                (novo_usuario, generate_password_hash(nova_senha)),
            )
            conn.commit()
            session["usuario"] = novo_usuario
            flash("Usuário e senha atualizados com sucesso.", "success")
        conn.close()
        return redirect(url_for("conta"))

    row = conn.execute("SELECT * FROM login_config WHERE id=1").fetchone()
    conn.close()
    return render_template("conta.html", usuario_atual=row["usuario"])


# ---------- Empresa ----------

@app.route("/empresa", methods=["GET", "POST"])
def empresa():
    conn = get_conn()
    if request.method == "POST":
        logo_file = request.files.get("logo")
        row_atual = conn.execute("SELECT logo_data, logo_mimetype FROM empresa WHERE id=1").fetchone()
        logo_data = row_atual["logo_data"] if row_atual else None
        logo_mimetype = row_atual["logo_mimetype"] if row_atual else None
        if logo_file and logo_file.filename:
            logo_data = logo_file.read()
            logo_mimetype = logo_file.mimetype

        try:
            porta = int(request.form.get("smtp_porta") or 587)
        except ValueError:
            porta = 587

        conn.execute(
            """UPDATE empresa SET nome=?, cnpj=?, endereco=?, telefone=?, email=?, logo_data=?, logo_mimetype=?,
                smtp_servidor=?, smtp_porta=?, smtp_usuario=?, smtp_senha=? WHERE id=1""",
            (
                request.form.get("nome"), request.form.get("cnpj"),
                request.form.get("endereco"), request.form.get("telefone"),
                request.form.get("email"), psycopg2.Binary(logo_data) if logo_data else None, logo_mimetype,
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


@app.route("/empresa/logo")
def empresa_logo():
    conn = get_conn()
    row = conn.execute("SELECT logo_data, logo_mimetype FROM empresa WHERE id=1").fetchone()
    conn.close()
    if not row or not row["logo_data"]:
        return "", 404
    return app.response_class(bytes(row["logo_data"]), mimetype=row["logo_mimetype"] or "image/png")


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


@app.route("/orcamentos", methods=["GET"])
def listar_orcamentos():
    busca = request.args.get("busca", "").strip()
    data_inicio = request.args.get("data_inicio", "").strip()
    data_fim = request.args.get("data_fim", "").strip()

    query = """
        SELECT o.*, c.nome AS cliente_nome
        FROM orcamentos o
        JOIN clientes c ON c.id = o.cliente_id
        WHERE 1=1
    """
    params = []
    if busca:
        query += " AND c.nome ILIKE ?"
        params.append(f"%{busca}%")
    if data_inicio:
        query += " AND o.data >= ?"
        params.append(data_inicio)
    if data_fim:
        query += " AND o.data <= ?"
        params.append(data_fim)
    query += " ORDER BY o.id DESC"

    conn = get_conn()
    rows = conn.execute(query, tuple(params)).fetchall()
    conn.close()
    return render_template(
        "orcamentos_lista.html", orcamentos=rows,
        busca=busca, data_inicio=data_inicio, data_fim=data_fim,
    )


def _carregar_dados_form_orcamento():
    conn = get_conn()
    clientes_rows = conn.execute("SELECT * FROM clientes ORDER BY nome").fetchall()
    produtos_rows = conn.execute("SELECT * FROM produtos ORDER BY descricao").fetchall()
    mo_rows = conn.execute("SELECT * FROM mao_de_obra ORDER BY descricao").fetchall()
    conn.close()

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
    return clientes_rows, catalogo_json


@app.route("/orcamento/novo", methods=["GET"])
def novo_orcamento():
    clientes_rows, catalogo_json = _carregar_dados_form_orcamento()
    return render_template(
        "orcamento.html",
        clientes=clientes_rows,
        catalogo_json=json.dumps(catalogo_json),
        orcamento=None,
        itens_existentes_json="[]",
        form_action=url_for("criar_orcamento"),
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


@app.route("/orcamento/<int:orcamento_id>/editar", methods=["GET", "POST"])
def editar_orcamento(orcamento_id):
    conn = get_conn()
    orcamento = conn.execute("SELECT * FROM orcamentos WHERE id=?", (orcamento_id,)).fetchone()
    if not orcamento:
        conn.close()
        return "Não encontrado", 404

    if request.method == "POST":
        cliente_id = request.form.get("cliente_id")
        validade = request.form.get("validade_dias") or 15
        observacoes = request.form.get("observacoes") or ""
        itens_json = request.form.get("itens_json") or "[]"

        try:
            itens = json.loads(itens_json)
        except json.JSONDecodeError:
            itens = []

        if not cliente_id or not itens:
            conn.close()
            flash("Selecione um cliente e adicione ao menos um item.", "error")
            return redirect(url_for("editar_orcamento", orcamento_id=orcamento_id))

        total = sum(float(i["valor_total"]) for i in itens)

        conn.execute(
            "UPDATE orcamentos SET cliente_id=?, validade_dias=?, observacoes=?, total=? WHERE id=?",
            (cliente_id, int(validade), observacoes, total, orcamento_id),
        )
        conn.execute("DELETE FROM orcamento_itens WHERE orcamento_id=?", (orcamento_id,))
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
        orcamento_atualizado = conn.execute("SELECT * FROM orcamentos WHERE id=?", (orcamento_id,)).fetchone()
        itens_db = conn.execute("SELECT * FROM orcamento_itens WHERE orcamento_id=?", (orcamento_id,)).fetchall()
        conn.close()

        gerar_pdf_orcamento(empresa, cliente, orcamento_atualizado, itens_db)

        flash("Orçamento atualizado e PDF regerado com sucesso.", "success")
        return redirect(url_for("ver_orcamento", orcamento_id=orcamento_id))

    itens_db = conn.execute("SELECT * FROM orcamento_itens WHERE orcamento_id=?", (orcamento_id,)).fetchall()
    clientes_rows, catalogo_json = _carregar_dados_form_orcamento()
    conn.close()

    itens_existentes = [
        {
            "tipo": i["tipo"], "descricao": i["descricao"], "unidade": i["unidade"],
            "quantidade": i["quantidade"], "valor_unitario": i["valor_unitario"], "valor_total": i["valor_total"],
        }
        for i in itens_db
    ]

    return render_template(
        "orcamento.html",
        clientes=clientes_rows,
        catalogo_json=json.dumps(catalogo_json),
        orcamento=orcamento,
        itens_existentes_json=json.dumps(itens_existentes),
        form_action=url_for("editar_orcamento", orcamento_id=orcamento_id),
    )


@app.route("/orcamento/<int:orcamento_id>")
def ver_orcamento(orcamento_id):
    conn = get_conn()
    orcamento = conn.execute("SELECT * FROM orcamentos WHERE id=?", (orcamento_id,)).fetchone()
    if not orcamento:
        conn.close()
        return "Não encontrado", 404
    cliente = conn.execute("SELECT * FROM clientes WHERE id=?", (orcamento["cliente_id"],)).fetchone()
    itens = conn.execute("SELECT * FROM orcamento_itens WHERE orcamento_id=?", (orcamento_id,)).fetchall()
    conn.close()
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
