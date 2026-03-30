import json
import datetime
import os
from pathlib import Path

# 直接导入原项目核心函数（完全兼容，无修改）
from daily_arxiv import fetch_arxiv_papers
from ai import generate_ai_content

# 导入邮件工具
from email_sender import send_user_email

# 加载配置文件
USER_CONFIG_PATH = Path(__file__).parent / "users.json"
with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
    USER_LIST = json.load(f)

# 全局时间判断
TODAY = datetime.date.today()
WEEKDAY = TODAY.weekday()  # 0=周一，6=周日
DAY = TODAY.day            # 日期

def check_send_time(freq: str) -> bool:
    """判断是否满足用户的推送频次要求"""
    if freq == "daily":
        return True
    if freq == "weekly" and WEEKDAY == 0:
        return True
    if freq == "monthly" and DAY == 1:
        return True
    return False

def generate_user_report(user: dict, papers: list) -> str:
    """为用户生成个性化AI论文报告"""
    username = user["username"]
    freq = user["frequency"]
    keywords = user["keywords"]
    
    report = f"===== {username} 的 {freq} 论文推送 =====\n"
    report += f"推送时间：{TODAY}\n"
    report += f"订阅领域：{user['categories']}\n"
    report += f"关注关键词：{', '.join(keywords)}\n\n"
    
    if not papers:
        report += "今日无符合条件的新论文～\n"
        return report
    
    # 遍历论文，添加AI摘要
    for idx, paper in enumerate(papers, 1):
        # 调用原项目AI生成内容
        ai_summary = generate_ai_content(paper["summary"])
        
        report += f"📌 论文 {idx}\n"
        report += f"标题：{paper['title']}\n"
        report += f"作者：{paper['authors']}\n"
        report += f"领域：{paper['category']}\n"
        report += f"AI中英文摘要：\n{ai_summary}\n"
        report += f"链接：{paper['link']}\n"
        report += "-" * 60 + "\n"
    
    return report

def main():
    """主函数：遍历所有用户，执行个性化推送"""
    print("===== 多用户 arXiv AI 推送任务启动 =====")
    
    for user in USER_LIST:
        username = user["username"]
        email = user["email"]
        categories = user["categories"]
        freq = user["frequency"]
        
        # 1. 判断是否需要推送
        if not check_send_time(freq):
            print(f"⏳ {username} 今日不推送（频次：{freq}）")
            continue
        
        print(f"\n🔍 开始处理用户：{username} | 邮箱：{email}")
        
        # 2. 调用原项目函数，爬取对应领域论文（自带去重）
        papers = fetch_arxiv_papers(categories=categories, max_results=10)
        
        # 3. 生成报告
        report = generate_user_report(user, papers)
        
        # 4. 发送邮件
        send_user_email(email, username, report)
    
    print("\n===== 所有用户任务执行完毕 =====")

if __name__ == "__main__":
    main()
