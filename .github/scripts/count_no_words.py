import json
import os
import sys

from actions_toolkit import github

if __name__ == "__main__":
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

    # get octokit instance
    octokit = github.get_octokit(GITHUB_TOKEN)
    # get context
    context = github.Context()

    # extract repo
    repo = octokit.rest.get_repo(f"{context.repo.owner}/{context.repo.repo}")

    # get issue number
    ISSUE_NUMBER = context.issue.number
    issue = repo.get_issue(ISSUE_NUMBER)

    # get changed files
    changed_files = os.getenv("CHANGED_FILES")
    changed_files = json.loads(changed_files)

    removed_files = os.getenv("REMOVED_FILES")
    removed_files = json.loads(removed_files)

    changed_files = [f for f in changed_files if f not in removed_files]

    # filter out only markdown files
    md_files = [f for f in changed_files if f.endswith(".mdx") and os.path.exists(f)]

    if not md_files:
        issue.create_comment("No markdown files changed.")
        sys.exit(0)

    # read content of each file
    word_count = {}
    for filename in md_files:
        with open(filename, "r") as f:
            content = f.read()
            # delete common markdown symbols

            content = (
                content.replace('"', "")
                .replace("*", "")
                .replace("(", "")
                .replace(")", "")
                .replace("!", "")
                .replace("[", "")
                .replace("]", "")
                .replace("#", "")
                .replace(">", "")
                .replace("`", "")
            )

            # count words
            word_count[filename] = len(content.split())

    # list all files and their word count
    comment = "Number of words in the following Markdown files have changed:\n"
    for filename, count in word_count.items():
        comment += f"- **{filename}** - *{count} words*\n"

    issue.create_comment(comment)
