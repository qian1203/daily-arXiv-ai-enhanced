# 兼容Python3.10+，原项目环境直接运行
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
import os

# 从GitHub Secrets读取配置，不硬编码隐私信息
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")  # 邮箱授权码，非登录密码

def send_user_email(to_email: str, username: str, report_content: str):
    """
    向单个用户发送论文推送邮件
    :param to_email: 用户收件邮箱
    :param username: 用户昵称
    :param report_content: 论文报告内容
    """
    try:
        # 构造邮件内容
        msg = MIMEText(report_content, "plain", "utf-8")
        msg["From"] = formataddr(["arXiv AI 论文推送", SMTP_USER])
        msg["To"] = formataddr([username, to_email])
        msg["Subject"] = f"【论文订阅】{username} 的个性化arXiv推送"

        # 发送邮件（SSL加密）
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [to_email], msg.as_string())
        
        print(f"✅ 邮件发送成功：{to_email}")
        return True

    except Exception as e:
        print(f"❌ 邮件发送失败：{to_email}，错误：{str(e)}")
        return False
