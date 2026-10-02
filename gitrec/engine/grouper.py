import re
import os
from typing import List, Dict, Set, Any
from datetime import timedelta
from gitrec.models.base import CommitModel, PullRequestModel, IssueModel, WorkItemModel, WorkType, WorkItemStatus, KanbanStatus
from gitrec.engine.relationship import RelationshipEngine


class DisjointSet:
    def __init__(self):
        self.parent = {}
        self.rank = {}

    def find(self, item: str) -> str:
        if item not in self.parent:
            self.parent[item] = item
            self.rank[item] = 0
            return item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, item1: str, item2: str):
        root1 = self.find(item1)
        root2 = self.find(item2)
        if root1 != root2:
            if self.rank[root1] < self.rank[root2]:
                self.parent[root1] = root2
            elif self.rank[root1] > self.rank[root2]:
                self.parent[root2] = root1
            else:
                self.parent[root2] = root1
                self.rank[root1] += 1


class WorkGrouper:
    def __init__(self, commits: List[CommitModel], prs: List[PullRequestModel], issues: List[IssueModel], proximity_hours: int = 24):
        self.commits = {c.sha: c for c in commits}
        self.prs = {p.number: p for p in prs}
        self.issues = {i.number: i for i in issues}
        self.proximity_hours = proximity_hours
        self.rel_engine = RelationshipEngine(commits, prs, issues)

    def _extract_module(self, filepath: str) -> str:
        parts = filepath.strip("/").split("/")
        if len(parts) > 1:
            return parts[0]
        return "root"

    def _format_standard_title(self, raw_title: str, modules: List[str]) -> str:
        """
        Formats title into standard: <Action> <object/component> [optional context]
        Example: "Implement tenant authentication in webserver"
        """
        if not raw_title:
            return "Perform maintenance and updates"

        # Check for conventional prefix intent before stripping
        prefix_intent = None
        m_conv = re.match(r"^([a-zA-Z]+)(?:\([^)]+\))?:\s*", raw_title)
        if m_conv:
            tag = m_conv.group(1).lower()
            if tag in ["fix", "hotfix", "bugfix"]:
                prefix_intent = "Fix"
            elif tag in ["feat", "feature"]:
                prefix_intent = "Implement"
            elif tag in ["docs", "doc"]:
                prefix_intent = "Document"
            elif tag in ["refactor"]:
                prefix_intent = "Refactor"
            elif tag in ["perf"]:
                prefix_intent = "Optimize"
            elif tag in ["test", "tests"]:
                prefix_intent = "Test"
            elif tag in ["chore", "build", "ci"]:
                prefix_intent = "Update"

        # Strip conventional commit prefixes like feat(core): or fix: or (#123)
        cleaned = re.sub(r"^[a-zA-Z]+(?:\([^)]+\))?:\s*", "", raw_title).strip()
        cleaned = re.sub(r"\(#\d+\)", "", cleaned).strip()
        cleaned = re.sub(r"#\d+", "", cleaned).strip()
        cleaned = cleaned.strip(" -:.")

        if not cleaned:
            cleaned = "Perform maintenance task"

        # Action normalization map
        action_map = {
            "add": "Add",
            "added": "Add",
            "adding": "Add",
            "implement": "Implement",
            "implemented": "Implement",
            "implementing": "Implement",
            "fix": "Fix",
            "fixed": "Fix",
            "fixing": "Fix",
            "update": "Update",
            "updated": "Update",
            "updating": "Update",
            "refactor": "Refactor",
            "refactored": "Refactor",
            "refactoring": "Refactor",
            "remove": "Remove",
            "removed": "Remove",
            "removing": "Remove",
            "delete": "Remove",
            "enable": "Enable",
            "disable": "Disable",
            "optimize": "Optimize",
            "upgrade": "Upgrade",
            "bump": "Upgrade",
            "clean": "Cleanup",
            "cleanup": "Cleanup",
            "document": "Document",
            "docs": "Document",
            "support": "Support",
            "configure": "Configure",
            "resolve": "Resolve",
            "prevent": "Prevent",
            "handle": "Handle"
        }

        words = cleaned.split()
        first_word = words[0].lower() if words else ""

        if first_word in action_map:
            words[0] = action_map[first_word]
        elif prefix_intent:
            words.insert(0, prefix_intent)
        else:
            if first_word.endswith("ing"):
                words[0] = first_word.capitalize()
            else:
                words.insert(0, "Implement")

        formatted_title = " ".join(words).strip()
        if formatted_title:
            formatted_title = formatted_title[0].upper() + formatted_title[1:]

        return formatted_title

    def group_work(self) -> List[WorkItemModel]:
        ds = DisjointSet()
        evidence_map: Dict[str, List[str]] = {}
        hierarchical_parent_links: Dict[str, str] = {}  # child_entity -> parent_entity

        # Register all entities
        for sha in self.commits:
            ds.find(f"commit:{sha}")
        for pr_num in self.prs:
            ds.find(f"pr:{pr_num}")
        for issue_num in self.issues:
            ds.find(f"issue:{issue_num}")

        # 1. Apply links from RelationshipEngine
        links = self.rel_engine.detect_links()
        for link in links:
            s, t = link["source"], link["target"]
            l_type = link.get("type", "")

            # If it's a hierarchical link, track it for parent-child assignment instead of flat union
            if l_type in ["issue_child_of_issue", "pr_child_of_issue", "pr_child_of_pr"]:
                hierarchical_parent_links[s] = t
            else:
                ds.union(s, t)
                root = ds.find(s)
                evidence_map.setdefault(root, []).append(link["evidence"])

        # 2. Heuristic Grouping: Conventional commit scope matching
        scope_pattern = re.compile(r"^[a-zA-Z]+(?:\(([^)]+)\))?:")
        commits_by_scope: Dict[str, List[CommitModel]] = {}
        for c in self.commits.values():
            m = scope_pattern.match(c.message.splitlines()[0]) if c.message else None
            if m and m.group(1):
                scope = m.group(1).lower().strip()
                commits_by_scope.setdefault(scope, []).append(c)

        for scope, scoped_commits in commits_by_scope.items():
            if len(scoped_commits) > 1:
                sorted_sc = sorted(scoped_commits, key=lambda x: x.timestamp)
                for i in range(len(sorted_sc) - 1):
                    c1, c2 = sorted_sc[i], sorted_sc[i+1]
                    if (c2.timestamp - c1.timestamp) <= timedelta(hours=self.proximity_hours * 2):
                        ds.union(f"commit:{c1.sha}", f"commit:{c2.sha}")
                        root = ds.find(f"commit:{c1.sha}")
                        evidence_map.setdefault(root, []).append(
                            f"Commits {c1.short_sha} & {c2.short_sha} share scope '({scope})' within time window"
                        )

        # 3. Semantic Topic & Module Proximity Clustering
        sorted_commits = sorted(self.commits.values(), key=lambda x: x.timestamp)
        stop_words = {"add", "added", "fix", "fixed", "update", "updated", "refactor", "cleanup", "the", "a", "an", "for", "to", "in", "on", "of", "and", "with"}
        
        for i in range(len(sorted_commits)):
            c1 = sorted_commits[i]
            c1_words = {w.lower() for w in re.findall(r'\b[a-zA-Z]{3,}\b', c1.message)} - stop_words
            c1_modules = {self._extract_module(f) for f in c1.changed_files if f}

            for j in range(i + 1, min(i + 15, len(sorted_commits))):
                c2 = sorted_commits[j]
                time_diff = (c2.timestamp - c1.timestamp)
                if time_diff > timedelta(hours=self.proximity_hours * 2):
                    break

                if c1.author_email == c2.author_email or c1.author_name == c2.author_name:
                    c2_words = {w.lower() for w in re.findall(r'\b[a-zA-Z]{3,}\b', c2.message)} - stop_words
                    c2_modules = {self._extract_module(f) for f in c2.changed_files if f}
                    
                    shared_topics = c1_words & c2_words
                    shared_modules = c1_modules & c2_modules

                    # Case A: Shared specific functional keyword (e.g., 'registration') on same module
                    if shared_topics and (shared_modules or not c1_modules):
                        ds.union(f"commit:{c1.sha}", f"commit:{c2.sha}")
                        root = ds.find(f"commit:{c1.sha}")
                        topic_str = ", ".join(list(shared_topics)[:2])
                        evidence_map.setdefault(root, []).append(
                            f"Commits {c1.short_sha} & {c2.short_sha} share topic '{topic_str}' within time window"
                        )
                    # Case B: Direct follow-up fix/test/refactor on same module
                    elif shared_modules and (c2.timestamp - c1.timestamp) <= timedelta(hours=self.proximity_hours):
                        c2_first_line = c2.message.splitlines()[0].lower() if c2.message else ""
                        if any(c2_first_line.startswith(prefix) for prefix in ["fix", "test", "wip", "update", "refactor", "cleanup", "typo"]):
                            ds.union(f"commit:{c1.sha}", f"commit:{c2.sha}")
                            root = ds.find(f"commit:{c1.sha}")
                            evidence_map.setdefault(root, []).append(
                                f"Follow-up commit {c2.short_sha} by {c1.author_name} on overlapping module within {self.proximity_hours}h"
                            )


        # 4. Aggregate clusters
        clusters: Dict[str, Dict[str, Any]] = {}
        for sha, commit in self.commits.items():
            root = ds.find(f"commit:{sha}")
            clusters.setdefault(root, {"commits": [], "prs": [], "issues": []})["commits"].append(commit)
        
        for pr_num, pr in self.prs.items():
            root = ds.find(f"pr:{pr_num}")
            clusters.setdefault(root, {"commits": [], "prs": [], "issues": []})["prs"].append(pr)

        for iss_num, iss in self.issues.items():
            root = ds.find(f"issue:{iss_num}")
            clusters.setdefault(root, {"commits": [], "prs": [], "issues": []})["issues"].append(iss)

        # Map cluster root to work item ID
        cluster_root_to_id: Dict[str, str] = {}
        # Map raw entity (e.g. "issue:123") to work item ID
        entity_to_id: Dict[str, str] = {}

        raw_items: List[WorkItemModel] = []
        item_counter = 1

        # Track minor orphan commits to group into monthly maintenance epics
        monthly_orphan_commits: Dict[str, List[CommitModel]] = {}

        for root, data in clusters.items():
            c_list: List[CommitModel] = data["commits"]
            p_list: List[PullRequestModel] = data["prs"]
            i_list: List[IssueModel] = data["issues"]

            if not c_list and not p_list and not i_list:
                continue

            # Detect if this cluster is a minor orphan commit (single commit, no PR/Issue, trivial message or docs typo)
            if not p_list and not i_list and len(c_list) == 1:
                single_commit = c_list[0]
                first_msg = single_commit.message.splitlines()[0].lower() if single_commit.message else ""
                is_minor = any(first_msg.startswith(prefix) for prefix in ["fix typo", "typo", "doc:", "docs:", "chore:", "cleanup", "formatting", "lint", "bump"]) or len(first_msg) < 15
                if is_minor:
                    month_key = single_commit.timestamp.strftime("%Y-%m")
                    monthly_orphan_commits.setdefault(month_key, []).append(single_commit)
                    continue

            # Determine title & description
            title = ""
            desc_parts = []
            if i_list:
                title = i_list[0].title
                if i_list[0].body:
                    desc_parts.append(i_list[0].body.strip())
            elif p_list:
                title = p_list[0].title
                if p_list[0].body:
                    desc_parts.append(p_list[0].body.strip())
            elif c_list:
                first_commit = sorted(c_list, key=lambda x: x.timestamp)[0]
                title = first_commit.message.splitlines()[0] if first_commit.message else "Untitled Work"
                desc_parts.append(first_commit.message.strip())

            # Associated commits
            if len(c_list) > 1:
                commit_summaries = []
                for c in sorted(c_list, key=lambda x: x.timestamp):
                    first_l = c.message.splitlines()[0] if c.message else "Empty commit message"
                    commit_summaries.append(f"- `{c.short_sha}`: {first_l}")
                desc_parts.append("\n**Associated Commits:**\n" + "\n".join(commit_summaries))

            # Comments
            all_comments = []
            for i in i_list:
                for comm in i.comments:
                    all_comments.append(f"**[Issue #{i.number}]** {comm}")
            for p in p_list:
                for comm in p.comments:
                    all_comments.append(f"**[PR #{p.number}]** {comm}")

            if all_comments:
                desc_parts.append("\n**Discussion & Review Comments:**\n" + "\n\n".join(all_comments[:10]))

            desc = "\n\n".join(part for part in desc_parts if part).strip()

            # Timestamps
            all_dates = [c.timestamp for c in c_list] + [p.created_at for p in p_list] + [i.created_at for i in i_list]
            first_activity = min(all_dates)
            last_activity = max(all_dates)

            # Authors
            authors = list({c.author_name for c in c_list if c.author_name} | {p.author for p in p_list if p.author} | {i.author for i in i_list if i.author})
            
            # Files & Modules
            affected_files_set = set()
            for c in c_list:
                affected_files_set.update(c.changed_files)
            affected_files = sorted(list(affected_files_set))
            affected_modules = sorted(list({self._extract_module(f) for f in affected_files if f}))

            # Clean & format title according to standard: <Action> <object/component> [optional context]
            title = self._format_standard_title(title, affected_modules)

            # Labels
            labels_set = set()
            for p in p_list:
                labels_set.update(p.labels)
            for i in i_list:
                labels_set.update(i.labels)

            for mod in affected_modules:
                if mod and mod not in ["root", "test", "tests"]:
                    labels_set.add(f"module:{mod}")

            if c_list:
                first_msg = c_list[0].message.lower()
                if first_msg.startswith("doc") or any("doc" in mod for mod in affected_modules):
                    labels_set.add("documentation")
                elif first_msg.startswith("fix"):
                    labels_set.add("bug")
                elif first_msg.startswith("feat"):
                    labels_set.add("feature")
                elif first_msg.startswith("refactor"):
                    labels_set.add("refactor")

            labels = sorted(list(labels_set))

            # Evidences
            all_evidences = []
            if root in evidence_map:
                all_evidences.extend(evidence_map[root])
            if len(c_list) > 1:
                all_evidences.append(f"Grouped {len(c_list)} related commits")
            if p_list:
                all_evidences.append(f"Associated with PR(s): {', '.join(f'#{p.number}' for p in p_list)}")
            if i_list:
                all_evidences.append(f"Associated with Issue(s): {', '.join(f'#{i.number}' for i in i_list)}")

            # Kanban Status
            has_open_pr = any(p.state == "open" for p in p_list)
            has_open_issue = any(i.state == "open" for i in i_list)
            ready_label_indicators = {"ready", "help wanted", "good first issue", "triaged", "accepted", "confirmed", "to do", "todo"}
            has_ready_label = any(lbl.lower() in ready_label_indicators for lbl in labels)
            has_milestone = any(bool(i.milestone) for i in i_list) or any(bool(p.milestone) for p in p_list)

            if has_open_pr:
                kanban_status = KanbanStatus.IN_PROGRESS
                all_evidences.append("Kanban: In Progress (Open Pull Request in flight)")
            elif has_open_issue and c_list:
                kanban_status = KanbanStatus.IN_PROGRESS
                all_evidences.append("Kanban: In Progress (Commits actively associated with Open Issue)")
            elif has_open_issue:
                if has_ready_label or has_milestone:
                    kanban_status = KanbanStatus.READY_FOR_DEV
                    all_evidences.append("Kanban: Ready For Development (Triaged/Milestoned Open Issue)")
                else:
                    kanban_status = KanbanStatus.BACKLOG
                    all_evidences.append("Kanban: Backlog (Untriaged Open Issue)")
            else:
                kanban_status = KanbanStatus.DONE
                all_evidences.append("Kanban: Done (Historical Commits / Closed Issue / Merged PR)")

            # Check if this item is marked as an Epic via label
            is_epic = "epic" in [lbl.lower() for lbl in labels]
            w_type = WorkType.EPIC if is_epic else WorkType.UNKNOWN

            item_id = f"H{item_counter:04d}"
            item_counter += 1
            cluster_root_to_id[root] = item_id

            # Register individual entities to this item_id
            for c in c_list:
                entity_to_id[f"commit:{c.sha}"] = item_id
            for p in p_list:
                entity_to_id[f"pr:{p.number}"] = item_id
            for i in i_list:
                entity_to_id[f"issue:{i.number}"] = item_id

            raw_items.append(WorkItemModel(
                id=item_id,
                title=title,
                description=desc,
                work_type=w_type,
                confidence=0.0,
                evidence=all_evidences,
                status=WorkItemStatus.INFERRED,
                kanban_status=kanban_status,
                commit_shas=[c.sha for c in c_list],
                pr_numbers=[p.number for p in p_list],
                issue_numbers=[i.number for i in i_list],
                authors=authors,
                first_activity=first_activity,
                last_activity=last_activity,
                affected_files=affected_files,
                affected_modules=affected_modules,
                labels=labels
            ))

        # 5. Create Monthly Maintenance Epics for minor orphan commits
        for month_str, orphan_commits in monthly_orphan_commits.items():
            if not orphan_commits:
                continue
            month_commits = sorted(orphan_commits, key=lambda x: x.timestamp)
            epic_id = f"H{item_counter:04d}"
            item_counter += 1

            all_authors = list({c.author_name for c in month_commits if c.author_name})
            all_files = sorted(list({f for c in month_commits for f in c.changed_files if f}))
            all_mods = sorted(list({self._extract_module(f) for f in all_files if f}))

            commit_summaries = []
            for c in month_commits:
                first_l = c.message.splitlines()[0] if c.message else "Empty commit message"
                commit_summaries.append(f"- `{c.short_sha}`: {first_l} (by {c.author_name})")

            epic_desc = f"Monthly Maintenance & Minor Improvements for **{month_str}**.\n\n" \
                        f"Aggregated {len(month_commits)} standalone maintenance/documentation/typo commits.\n\n" \
                        f"**Included Commits:**\n" + "\n".join(commit_summaries)

            raw_items.append(WorkItemModel(
                id=epic_id,
                title=f"Maintenance & Housekeeping - {month_str}",
                description=epic_desc,
                work_type=WorkType.MAINTENANCE,
                confidence=0.90,
                evidence=[f"Aggregated {len(month_commits)} standalone maintenance commits into monthly work item"],
                status=WorkItemStatus.INFERRED,
                kanban_status=KanbanStatus.DONE,
                commit_shas=[c.sha for c in month_commits],
                pr_numbers=[],
                issue_numbers=[],
                authors=all_authors,
                first_activity=min(c.timestamp for c in month_commits),
                last_activity=max(c.timestamp for c in month_commits),
                affected_files=all_files,
                affected_modules=all_mods,
                labels=["maintenance", "housekeeping"]
            ))

        # 6. Resolve Hierarchical Parent-Child relationships
        item_map = {item.id: item for item in raw_items}
        for child_entity, parent_entity in hierarchical_parent_links.items():
            child_item_id = entity_to_id.get(child_entity)
            parent_item_id = entity_to_id.get(parent_entity)

            if child_item_id and parent_item_id and child_item_id != parent_item_id:
                child_item = item_map.get(child_item_id)
                parent_item = item_map.get(parent_item_id)
                if child_item and parent_item:
                    child_item.parent_id = parent_item.id
                    if child_item.id not in parent_item.children_ids:
                        parent_item.children_ids.append(child_item.id)
                    child_item.evidence.append(f"Sub-task / Child of parent ticket [{parent_item.id}] {parent_item.title}")
                    if parent_item.work_type == WorkType.UNKNOWN:
                        parent_item.work_type = WorkType.EPIC

        return sorted(raw_items, key=lambda w: w.first_activity)
