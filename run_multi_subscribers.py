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

def should_push(subscriber, now_utc):
    # 北京时间 = UTC时间 +8小时
    now_beijing = now_utc + timedelta(hours=8)
    current_hour = now_beijing.hour
    current_weekday = now_beijing.weekday()  # 0=周一，6=周日
    current_day = now_beijing.day

    # 🔴 核心修复：兼容 HH:MM 和 HH 两种格式，加异常兜底
    push_time_raw = subscriber.get("pushTime", "13")
    try:
        # 如果是 HH:MM 格式，拆分取小时部分
        if ":" in push_time_raw:
            push_hour = int(push_time_raw.split(":")[0])
        else:
            # 纯数字格式，直接转整数
            push_hour = int(push_time_raw)
    except (ValueError, TypeError):
        # 格式错误时，默认13点推送，避免整个任务崩溃
        print(f"⚠️  用户{subscriber.get('email')}的pushTime格式错误，使用默认13点推送")
        push_hour = 13

    frequency = subscriber.get("frequency", "daily")
    last_push = subscriber.get("lastPushDate")
    today_beijing = now_beijing.strftime("%Y-%m-%d")

    # 今天已经推送过，跳过重复发送
    if last_push == today_beijing:
        return False

    # 推送频次校验
    if frequency == "daily":
        # 工作日推送，且当前小时匹配
        return current_weekday < 5 and current_hour == push_hour
    elif frequency == "weekly":
        # 每周一推送，且当前小时匹配
        return current_weekday == 0 and current_hour == push_hour
    elif frequency == "monthly":
        # 每月1号推送，且当前小时匹配
        return current_day == 1 and current_hour == push_hour
    
    return False

def fetch_papers(categories, days=1):
    """爬取指定分类的论文"""
    all_papers = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # ✅ 修正2：兼容 arxiv 2.x 语法
    client = arxiv.Client()
    
    for category in categories:
        try:
            search = arxiv.Search(
                query=f"cat:{category}",
                max_results=20,
                sort_by=arxiv.SortCriterion.SubmittedDate
            )
            # 使用 client.results() 替代 search.results()
            for result in client.results(search):
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
    
    # 简单去重（避免同一篇论文属于多个分类被重复推送）
    seen_urls = set()
    unique_papers = []
    for p in all_papers:
        if p['url'] not in seen_urls:
            seen_urls.add(p['url'])
            unique_papers.append(p)
            
    return unique_papers[:30]

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
    msg['Subject'] = f"📚 arXiv每日论文推送 - {(datetime.now() + timedelta(hours=8)).strftime('%Y-%m-%d')}"

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

    # ✅ 修正3：兼容 SSL (465) 和 STARTTLS (587)
    try:
        if SMTP_PORT == 587:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Email sent successfully to {subscriber['email']}")
    except Exception as e:
        print(f"Failed to send email: {e}")
        raise e

def main():
    now_utc = datetime.utcnow()
    subscribers, sha = get_subscribers()
    updated_subscribers = subscribers.copy()
    has_updates = False

    # 🔴 新增：读取强制推送的用户ID（来自GitHub Actions输入）
    FORCE_PUSH_USER_ID = os.getenv("FORCE_PUSH_USER_ID", "")

    for i, subscriber in enumerate(subscribers):
        # 🔴 新增：判断是正常定时推送，还是强制手动推送
        is_normal_push = should_push(subscriber, now_utc)
        is_force_push = FORCE_PUSH_USER_ID and subscriber.get("id") == FORCE_PUSH_USER_ID

        if is_normal_push or is_force_push:
            print(f"Processing subscriber: {subscriber['email']}")
            if is_force_push:
                print(f"⚠️  强制推送模式：忽略时间/频次检查")
            
            # 确定爬取天数（强制推送默认爬1天）
            days = 1
            if subscriber['frequency'] == 'weekly' and not is_force_push:
                days = 7
            elif subscriber['frequency'] == 'monthly' and not is_force_push:
                days = 30
            
            # 爬取论文并生成摘要
            papers = fetch_papers(subscriber['categories'], days)
            for paper in papers:
                paper['summary'] = generate_summary(paper)
            
            # 发送邮件
            if papers:
                send_email(subscriber, papers)
                # 🔴 新增：强制推送时，不更新 lastPushDate（避免影响正常定时推送）
                if not is_force_push:
                    updated_subscribers[i]['lastPushDate'] = (now_utc + timedelta(hours=8)).strftime("%Y-%m-%d")
                    has_updates = True
                print(f"Push sent to {subscriber['email']}")
    
    # 更新订阅者配置（仅正常推送时更新）
    if has_updates:
        update_subscribers(updated_subscribers, sha)
        print("Subscribers updated.")

if __name__ == "__main__":
    main()
