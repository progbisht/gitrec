import re
from typing import List, Dict, Any, Optional
from gitrec.models.base import WorkItemModel, WorkType, WorkItemStatus
from gitrec.storage.db import Storage
from gitrec.jira.client import JiraClient


class JiraMigrator:
    """
    Handles idempotent migration of approved WorkItems to Jira.
    """

    DEFAULT_TYPE_MAP = {
        WorkType.EPIC: "Epic",
        WorkType.FEATURE: "Story",
        WorkType.BUG: "Bug",
        WorkType.TASK: "Task",
        WorkType.IMPROVEMENT: "Task",
        WorkType.REFACTOR: "Task",
        WorkType.PERFORMANCE: "Task",
        WorkType.SECURITY: "Bug",
        WorkType.INFRASTRUCTURE: "Task",
        WorkType.DOCUMENTATION: "Task",
        WorkType.TEST: "Task",
        WorkType.CHORE: "Task",
        WorkType.CONFIGURATION: "Task",
        WorkType.DEPENDENCY: "Task",
        WorkType.TECHNICAL_DEBT: "Task",
        WorkType.MAINTENANCE: "Task",
        WorkType.SUB_TASK: "Subtask",
        WorkType.UNKNOWN: "Task"
    }


    def __init__(self, jira_client: Optional[JiraClient], storage: Storage, project_key: str, type_map: Optional[Dict[WorkType, str]] = None, dry_run: bool = False):
        self.client = jira_client
        self.storage = storage
        self.project_key = project_key
        self.type_map = type_map or self.DEFAULT_TYPE_MAP.copy()
        self.dry_run = dry_run

        # Auto-align issue types if client is connected
        if self.client and not dry_run:
            try:
                p_info = self.client.get_project(project_key)
                avail_types = {it['name'].lower(): it['name'] for it in p_info.get('issueTypes', [])}
                for wt, target_name in list(self.type_map.items()):
                    t_lower = target_name.lower()
                    if t_lower in avail_types:
                        self.type_map[wt] = avail_types[t_lower]
                    elif t_lower in ["subtask", "sub-task"] and "subtask" in avail_types:
                        self.type_map[wt] = avail_types["subtask"]
                    elif t_lower in ["subtask", "sub-task"] and "sub-task" in avail_types:
                        self.type_map[wt] = avail_types["sub-task"]
            except Exception:
                pass

    def _parse_markdown_inlines(self, text: str) -> List[Dict[str, Any]]:
        """Parse basic markdown text into Jira ADF inline nodes with marks."""
        # Regex tokens for code, bold, link, plain text
        token_pattern = re.compile(r'(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))')
        parts = token_pattern.split(text)
        inlines = []
        for part in parts:
            if not part:
                continue
            if part.startswith("`") and part.endswith("`") and len(part) >= 2:
                inlines.append({
                    "type": "text",
                    "text": part[1:-1],
                    "marks": [{"type": "code"}]
                })
            elif part.startswith("**") and part.endswith("**") and len(part) >= 4:
                inlines.append({
                    "type": "text",
                    "text": part[2:-2],
                    "marks": [{"type": "strong"}]
                })
            elif part.startswith("[") and "](" in part and part.endswith(")"):
                m = re.match(r'\[([^\]]+)\]\(([^)]+)\)', part)
                if m:
                    inlines.append({
                        "type": "text",
                        "text": m.group(1),
                        "marks": [{"type": "link", "attrs": {"href": m.group(2)}}]
                    })
                else:
                    inlines.append({"type": "text", "text": part})
            else:
                inlines.append({"type": "text", "text": part})
        return inlines or [{"type": "text", "text": text}]

    def build_adf_description(self, item: WorkItemModel) -> Dict[str, Any]:
        """
        Build Jira Atlassian Document Format (ADF) description for Jira Cloud REST v3 with rich blocks,
        including dedicated Historical Development timeline and metadata panels.
        """
        content = [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": item.title}]
            }
        ]

        desc_raw = (item.description or "").strip()
        if desc_raw:
            paragraphs = desc_raw.split("\n\n")
            for para in paragraphs:
                para_stripped = para.strip()
                if not para_stripped:
                    continue

                lines = para_stripped.splitlines()
                # Check if this paragraph is a bullet list (lines starting with - or *)
                if all(line.strip().startswith(("-", "*")) for line in lines if line.strip()):
                    list_items = []
                    for line in lines:
                        cleaned_line = re.sub(r"^[-*]\s*", "", line.strip())
                        list_items.append({
                            "type": "listItem",
                            "content": [{
                                "type": "paragraph",
                                "content": self._parse_markdown_inlines(cleaned_line)
                            }]
                        })
                    content.append({
                        "type": "bulletList",
                        "content": list_items
                    })
                elif para_stripped.startswith("### ") or para_stripped.startswith("## "):
                    level = 3 if para_stripped.startswith("### ") else 2
                    heading_text = re.sub(r"^#+\s*", "", para_stripped)
                    content.append({
                        "type": "heading",
                        "attrs": {"level": level},
                        "content": [{"type": "text", "text": heading_text}]
                    })
                else:
                    content.append({
                        "type": "paragraph",
                        "content": self._parse_markdown_inlines(para_stripped)
                    })

        # Historical Development Timeline (Preserving historical development dates)
        content.extend([
            {"type": "rule"},
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "📅 Historical Development Timeline"}]
            }
        ])

        hist_timeline_items = [
            f"**First Commit Date:** {item.first_activity.strftime('%d %b %Y %H:%M UTC')}",
            f"**Last Commit / Resolved Date:** {item.last_activity.strftime('%d %b %Y %H:%M UTC')}",
            f"**Original Author / Assignee:** {', '.join(item.authors) if item.authors else 'Unknown'}",
            f"**Original Kanban Status:** {item.kanban_status.value}"
        ]
        if item.pr_numbers:
            hist_timeline_items.append(f"**Source GitHub PR:** {', '.join(f'#{n}' for n in item.pr_numbers)}")
        if item.issue_numbers:
            hist_timeline_items.append(f"**Source GitHub Issue:** {', '.join(f'#{n}' for n in item.issue_numbers)}")

        timeline_list_content = []
        for text in hist_timeline_items:
            timeline_list_content.append({
                "type": "listItem",
                "content": [{
                    "type": "paragraph",
                    "content": self._parse_markdown_inlines(text)
                }]
            })

        content.append({
            "type": "bulletList",
            "content": timeline_list_content
        })

        # Traceability & Git Commits
        content.extend([
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "📊 Traceability & Git Evidence"}]
            }
        ])

        bullet_items = [
            f"**Classification:** {item.work_type.value}",
            f"**Confidence Score:** {item.confidence:.2f}",
            f"**Affected Modules:** {', '.join(item.affected_modules) if item.affected_modules else 'root'}"
        ]

        if item.commit_shas:
            bullet_items.append(f"**Historical Git Commits ({len(item.commit_shas)}):** {', '.join(f'`{sha[:7]}`' for sha in item.commit_shas[:10])}{' ...' if len(item.commit_shas) > 10 else ''}")

        bullet_list_content = []
        for text in bullet_items:
            bullet_list_content.append({
                "type": "listItem",
                "content": [{
                    "type": "paragraph",
                    "content": self._parse_markdown_inlines(text)
                }]
            })

        content.append({
            "type": "bulletList",
            "content": bullet_list_content
        })

        if item.evidence:
            content.append({
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "🔎 Grouping & Classification Evidence"}]
            })
            ev_list_content = []
            for ev in item.evidence:
                ev_list_content.append({
                    "type": "listItem",
                    "content": [{
                        "type": "paragraph",
                        "content": self._parse_markdown_inlines(ev)
                    }]
                })
            content.append({
                "type": "bulletList",
                "content": ev_list_content
            })

        return {
            "type": "doc",
            "version": 1,
            "content": content
        }

    def build_description(self, item: WorkItemModel) -> str:
        lines = [
            f"h3. Work Item: {item.title}",
            f"{item.description or item.title}",
            "",
            "----",
            "h4. Historical Development Timeline",
            f"* *First Commit Date:* {item.first_activity.strftime('%d %b %Y %H:%M UTC')}",
            f"* *Last Commit / Resolved Date:* {item.last_activity.strftime('%d %b %Y %H:%M UTC')}",
            f"* *Original Author:* {', '.join(item.authors) if item.authors else 'Unknown'}",
            f"* *Original Status:* {item.kanban_status.value}"
        ]

        if item.pr_numbers:
            lines.append(f"* *Source GitHub PR:* {', '.join(f'#{n}' for n in item.pr_numbers)}")
        if item.issue_numbers:
            lines.append(f"* *Source GitHub Issue:* {', '.join(f'#{n}' for n in item.issue_numbers)}")

        lines.extend([
            "",
            "h4. Traceability & Git Evidence",
            f"* *Confidence Score:* {item.confidence:.2f}",
            f"* *Classification:* {item.work_type.value}",
            f"* *Affected Modules:* {', '.join(item.affected_modules) if item.affected_modules else 'root'}"
        ])

        if item.commit_shas:
            lines.append(f"* *Historical Git Commits ({len(item.commit_shas)}):* {', '.join(sha[:7] for sha in item.commit_shas[:10])}{' ...' if len(item.commit_shas) > 10 else ''}")

        if item.evidence:
            lines.append("")
            lines.append("h4. Grouping & Scoring Evidence")
            for ev in item.evidence:
                lines.append(f"# {ev}")

        return "\n".join(lines)



    def _transition_to_kanban_status(self, jira_key: str, target_kanban_status: str):
        if not self.client:
            return
        try:
            transitions = self.client.get_transitions(jira_key)
            target_lower = target_kanban_status.lower()
            
            # Find best matching transition
            matching_trans = None
            for t in transitions:
                name = t.get("name", "").lower()
                to_status = t.get("to", {}).get("name", "").lower()
                if target_lower in name or target_lower in to_status:
                    matching_trans = t
                    break
            
            if matching_trans:
                self.client.transition_issue(jira_key, matching_trans["id"])
        except Exception:
            pass

    def migrate(self, items: List[WorkItemModel]) -> List[Dict[str, Any]]:
        existing_mappings = self.storage.get_jira_mappings()
        results = []

        for item in items:
            # Skip excluded items
            if item.status == WorkItemStatus.EXCLUDED:
                results.append({
                    "id": item.id,
                    "status": "skipped",
                    "reason": "Work item is marked as Excluded"
                })
                continue

            jira_type = self.type_map.get(item.work_type, "Task")
            # Summary title
            summary = item.title.strip()
            description_text = self.build_description(item)
            description_adf = self.build_adf_description(item)
            kanban_label = "kanban_" + re.sub(r'[^a-zA-Z0-9_-]', '_', item.kanban_status.value.lower())

            # Try creating/updating using REST v3 with ADF, with graceful fallback to REST v2
            fields_v3 = {
                "project": {"key": self.project_key},
                "summary": summary[:250],
                "description": description_adf,
                "issuetype": {"name": jira_type},
                "labels": ["gitrec-backfill", kanban_label] + [re.sub(r'[^a-zA-Z0-9_-]', '_', lbl) for lbl in item.labels]
            }

            fields_v2 = {
                "project": {"key": self.project_key},
                "summary": summary[:250],
                "description": description_text,
                "issuetype": {"name": jira_type},
                "labels": ["gitrec-backfill", kanban_label] + [re.sub(r'[^a-zA-Z0-9_-]', '_', lbl) for lbl in item.labels]
            }

            # If this work item is a sub-task or has a parent, attach the parent Jira key
            if item.parent_id and item.parent_id in existing_mappings:
                parent_jira_key = existing_mappings[item.parent_id]["jira_key"]
                fields_v3["parent"] = {"key": parent_jira_key}
                fields_v2["parent"] = {"key": parent_jira_key}

            # Check if already migrated (idempotency)
            if item.id in existing_mappings:
                mapping = existing_mappings[item.id]
                jira_key = mapping["jira_key"]

                if self.dry_run:
                    results.append({
                        "id": item.id,
                        "jira_key": jira_key,
                        "status": "dry-run-update",
                        "issue_type": jira_type,
                        "kanban_status": item.kanban_status.value
                    })
                else:
                    try:
                        # Attempt v3 with ADF update
                        try:
                            self.client.update_issue(jira_key, {
                                "summary": fields_v3["summary"],
                                "description": fields_v3["description"]
                            }, use_v3=True)
                        except Exception:
                            # Fallback to v2 with text
                            self.client.update_issue(jira_key, {
                                "summary": fields_v2["summary"],
                                "description": fields_v2["description"]
                            }, use_v3=False)

                        self._transition_to_kanban_status(jira_key, item.kanban_status.value)
                        item.jira_key = jira_key
                        item.status = WorkItemStatus.MIGRATED
                        item.jira_status = item.kanban_status.value
                        self.storage.update_work_item(item)
                        results.append({
                            "id": item.id,
                            "jira_key": jira_key,
                            "status": "updated",
                            "kanban_status": item.kanban_status.value
                        })
                    except Exception as e:
                        results.append({
                            "id": item.id,
                            "jira_key": jira_key,
                            "status": "error",
                            "error": str(e)
                        })
            else:
                # Create new issue
                if self.dry_run:
                    results.append({
                        "id": item.id,
                        "status": "dry-run-create",
                        "issue_type": jira_type,
                        "summary": summary,
                        "kanban_status": item.kanban_status.value
                    })
                else:
                    try:
                        created = None
                        try:
                            created = self.client.create_issue(fields_v3, use_v3=True)
                        except Exception:
                            created = self.client.create_issue(fields_v2, use_v3=False)

                        new_key = created["key"]
                        new_id = created.get("id", "")
                        
                        # Apply transition to match Kanban status
                        self._transition_to_kanban_status(new_key, item.kanban_status.value)

                        # Establish GitHub <-> Jira Relationships (Phase 6 Remote Links)
                        if self.client:
                            # 1. Link Pull Requests
                            for pr_num in item.pr_numbers:
                                pr_url = f"https://github.com/{self.project_key}/pull/{pr_num}"
                                self.client.create_remote_link(
                                    issue_key=new_key,
                                    url=pr_url,
                                    title=f"GitHub PR #{pr_num}: {item.title}",
                                    summary=f"Linked Pull Request #{pr_num} for {new_key}"
                                )
                            # 2. Link Commits if standalone
                            if not item.pr_numbers and item.commit_shas:
                                for sha in item.commit_shas[:3]:
                                    c_url = f"https://github.com/{self.project_key}/commit/{sha}"
                                    self.client.create_remote_link(
                                        issue_key=new_key,
                                        url=c_url,
                                        title=f"Git Commit {sha[:7]}",
                                        summary=f"Associated Git commit for {new_key}"
                                    )

                        self.storage.save_jira_mapping(
                            work_item_id=item.id,
                            jira_key=new_key,
                            jira_id=new_id,
                            issue_type=jira_type,
                            status=item.kanban_status.value
                        )
                        item.jira_key = new_key
                        item.status = WorkItemStatus.MIGRATED
                        item.jira_status = item.kanban_status.value
                        self.storage.update_work_item(item)
                        results.append({
                            "id": item.id,
                            "jira_key": new_key,
                            "status": "created",
                            "kanban_status": item.kanban_status.value
                        })

                    except Exception as e:
                        results.append({
                            "id": item.id,
                            "status": "error",
                            "error": str(e)
                        })


        return results

