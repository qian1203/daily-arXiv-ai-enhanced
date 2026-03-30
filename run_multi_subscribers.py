import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from github import Github
import arxiv
from openai import OpenAI

# 初始化配置
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

REPO_OWNER = "qian1203"  # 替换为你的用户名
REPO_NAME = "daily-arXiv-ai-enhanced"

# 初始化客户端
github_client = Github(GITHUB_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

def get_subscribers():
    """读取订阅者配置"""
    repo = github_client.get_repo(f"{REPO_OWNER}/{REPO_NAME}")
    contents = repo.get_contents("subscribers.json")
    return json.loads(contents.decoded_content.decode()), contents.sha

def update_subscribers(subscribers, sha):
    """更新订阅者配置（更新lastPushDate）"""
    repo = github_client.get_repo(f"{REPO_OWNER}/{REPO_NAME}")
    repo.update_file(
        path="subscribers.json",
        message="Update last push dates",
        content=json.dumps(subscribers, indent=2),
        sha=sha
    )

def should_push(subscriber, now):
    """判断当前是否应该给该用户推送"""
    freq = subscriber["frequency"]
    push_hour = int(subscriber["pushTime"])
    last_push = subscriber.get("lastPushDate")
    today = now.strftime("%Y-%m-%d")
    current_hour = now.hour + 8  # UTC转北京时间

    # 检查时间是否匹配
    if current_hour != push_hour:
        return False
    # 检查今天是否已经推送过
    if last_push == today:
        return False
    
    # 检查频次
    weekday = now.weekday()  # 0=周一, 6=周日
    if freq == "daily" and weekday >= 5:
        return False  # 工作日推送，周末跳过
    if freq == "weekly" and weekday != 0:
        return False  # 仅周一推送
    if freq == "monthly" and now.day != 1:
        return False  # 仅每月1日推送
    
    return True

def fetch_papers(categories, days=1):
    """爬取指定分类的论文"""
    all_papers = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    for category in categories:
        try:
            search = arxiv.Search(
                query=f"cat:{category}",
                max_results=20,
                sort_by=arxiv.SortCriterion.SubmittedDate
            )
            for result in search.results():
                if result.published.date() >= start_date.date():
                    all_papers.append({
                        "title": result.title,
                        "authors": [a.name for a in result.authors],
                        "abstract": result.summary,
                        "url": result.entry_id,
                        "pdf_url": result.pdf_url,
                        "category": category
                    })
        except Exception as e:
            print(f"Error fetching {category}: {e}")
    return all_papers[:30]  # 限制最多30篇

def generate_summary(paper):
    """生成AI摘要"""
    prompt = f"""请用中文为以下arXiv论文生成一个100字以内的简洁摘要，突出核心贡献：
标题：{paper['title']}
摘要：{paper['abstract']}
"""
    try:
        response = openai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Summary error: {e}")
        return paper['abstract'][:100] + "..."

def send_email(subscriber, papers):
    """发送推送邮件"""
    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = subscriber['email']
    msg['Subject'] = f"📚 arXiv每日论文推送 - {datetime.now().strftime('%Y-%m-%d')}"

    # 构建邮件内容
    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto;">
        <h2 style="color: #2563eb;">📬 您的arXiv论文推送</h2>
        <p>以下是为您精选的 {', '.join(subscriber['categories'])} 分类论文：</p>
        <hr>
    """
    for paper in papers:
        html_content += f"""
        <div style="margin: 20px 0; padding: 15px; border: 1px solid #eee; border-radius: 8px;">
            <h3 style="margin: 0 0 10px 0;"><a href="{paper['pdf_url']}" style="color: #2563eb; text-decoration: none;">{paper['title']}</a></h3>
            <p style="color: #666; margin: 0 0 10px 0;">作者：{', '.join(paper['authors'][:3])}</p>
            <p style="margin: 0;">{paper['summary']}</p>
        </div>
        """
    html_content += """
        <hr>
        <p style="color: #999; font-size: 12px;">
            退订请回复本邮件，或访问仓库删除您的订阅配置。
        </p>
    </body>
    </html>
    """
    msg.attach(MIMEText(html_content, 'html'))

    # 发送邮件
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)

def main():
    now = datetime.utcnow()
    subscribers, sha = get_subscribers()
    updated_subscribers = subscribers.copy()

    for i, subscriber in enumerate(subscribers):
        if should_push(subscriber, now):
            print(f"Processing subscriber: {subscriber['email']}")
            
            # 确定爬取天数
            days = 1
            if subscriber['frequency'] == 'weekly':
                days = 7
            elif subscriber['frequency'] == 'monthly':
                days = 30
            
            # 爬取论文并生成摘要
            papers = fetch_papers(subscriber['categories'], days)
            for paper in papers:
                paper['summary'] = generate_summary(paper)
            
            # 发送邮件
            if papers:
                send_email(subscriber, papers)
                updated_subscribers[i]['lastPushDate'] = now.strftime("%Y-%m-%d")
                print(f"Push sent to {subscriber['email']}")
    
    # 更新订阅者配置
    if updated_subscribers != subscribers:
        update_subscribers(updated_subscribers, sha)

if __name__ == "__main__":
    main()
