import os
import re
from github import Github

SUMMARY_FILE = 'failures_artifacts/failures.txt'  # путь до summary

def parse_failures(path):
    """Разбиваем summary на отдельные ошибки, выделяем уникальный идентификатор."""
    with open(path, 'r') as f:
        content = f.read()

    # Регулярка: ищем все "Query unexpectedly failed (...)" и блок до следующего такого или конца файла
    pattern = r'(Query unexpectedly failed \([^\n]+\)[\s\S]+?)(?=^Query unexpectedly failed |\Z)'
    matches = re.finditer(pattern, content, re.MULTILINE)

    failures = []
    for match in matches:
        block = match.group(1)
        # Извлекаем строку уникальности:
        unique_line = re.search(r'Query unexpectedly failed \([^\n]+\)', block)
        unique_id = unique_line.group(0).strip() if unique_line else None
        failures.append({'unique': unique_id, 'block': block.strip()})
    return failures

def get_existing_issues(repo, query):
    """Поищем открытые issue с этим фрагментом."""
    # Можно искать по title, например:
    issues = repo.get_issues(state='open', labels=['ci-failure'])
    for issue in issues:
        if query in issue.title:
            return True
    return False

def main():
    token = os.environ["GITHUB_TOKEN"]
    job_name = os.environ.get("JOB_NAME", "CI Job")
    workflow_url = os.environ.get("WORKFLOW_URL", "")
    branch_label = os.environ.get("BRANCH_LABEL", "unknown-branch")

    # Репозиторий берем из GITHUB_REPOSITORY env или хардкодим если он другой
    repo_name = os.environ.get("GITHUB_REPOSITORY", "<TARGET_ORG>/<TARGET_REPO>")
    g = Github(token)
    repo = g.get_repo(repo_name)

    failures = parse_failures(SUMMARY_FILE)
    for fail in failures:
        unique_id = fail['unique']
        if not unique_id:
            continue
        title = f"[{job_name}] - {unique_id}"
        if get_existing_issues(repo, unique_id):
            print(f"Already exists: {title}")
            continue
        body = f"{fail['block']}\n\n[Workflow run]({workflow_url})"
        # Создаем issue с нужными лейблами
        issue = repo.create_issue(
            title=title,
            body=body,
            labels=[branch_label, 'ci-failure']
        )
        print(f"Created: {issue.html_url}")

if __name__ == "__main__":
    main()
