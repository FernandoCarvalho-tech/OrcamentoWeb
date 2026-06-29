import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication


def enviar_orcamento_email(empresa, destinatario, assunto, corpo, pdf_path):
    if not empresa["smtp_usuario"] or not empresa["smtp_senha"]:
        raise ValueError("Configuração de email (SMTP) não preenchida. Acesse Configurações da Empresa.")

    servidor = empresa["smtp_servidor"] or "smtp.gmail.com"
    porta = empresa["smtp_porta"] or 587

    msg = MIMEMultipart()
    msg["From"] = empresa["smtp_usuario"]
    msg["To"] = destinatario
    msg["Subject"] = assunto
    msg.attach(MIMEText(corpo, "plain"))

    with open(pdf_path, "rb") as f:
        part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
    part["Content-Disposition"] = f'attachment; filename="{os.path.basename(pdf_path)}"'
    msg.attach(part)

    with smtplib.SMTP(servidor, porta) as server:
        server.starttls()
        server.login(empresa["smtp_usuario"], empresa["smtp_senha"])
        server.send_message(msg)
