import subprocess
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from gitrec.models.base import CommitModel


class GitExtractor:
    def __init__(self, repo_path: str = "."):
        self.repo_path = os.path.abspath(repo_path)

    def _run_git(self, args: List[str]) -> str:
        cmd = ["git", "-C", self.repo_path] + args
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return res.stdout

    def extract_commits(self, branch: Optional[str] = None) -> List[CommitModel]:
        # Format separator
        # %H: commit hash, %h: abbreviated hash, %an: author name, %ae: author email
        # %cn: committer name, %ce: committer email, %aI: author date ISO 8601
        # %P: parent hashes, %B: raw body (unwrapped subject and body)
        sep = "___GITREC_COMMIT_SEP___"
        field_sep = "___GITREC_FIELD_SEP___"
        
        format_str = f"{sep}%H{field_sep}%h{field_sep}%an{field_sep}%ae{field_sep}%cn{field_sep}%ce{field_sep}%aI{field_sep}%P{field_sep}%B"
        
        args = ["log", "--all" if not branch else branch, f"--pretty=format:{format_str}", "--numstat"]
        output = self._run_git(args)
        
        raw_chunks = output.split(sep)
        commits = []
        
        for chunk in raw_chunks:
            if not chunk.strip():
                continue
            
            parts = chunk.split(field_sep)
            if len(parts) < 8:
                continue
            
            sha = parts[0].strip()
            short_sha = parts[1].strip()
            author_name = parts[2].strip()
            author_email = parts[3].strip()
            committer_name = parts[4].strip()
            committer_email = parts[5].strip()
            timestamp_str = parts[6].strip()
            parents_str = parts[7].strip()
            
            # The remaining part contains message + numstat lines
            rest = field_sep.join(parts[8:])
            
            # Extract numstat lines from rest
            lines = rest.splitlines()
            msg_lines = []
            numstat_lines = []
            
            in_numstat = False
            for line in lines:
                # numstat line: 10\t2\tpath/to/file.py or -\t-\tbinary.png
                parts_stat = line.split("\t")
                if len(parts_stat) == 3 and (parts_stat[0].isdigit() or parts_stat[0] == "-") and (parts_stat[1].isdigit() or parts_stat[1] == "-"):
                    numstat_lines.append(line)
                    in_numstat = True
                else:
                    if not in_numstat:
                        msg_lines.append(line)
            
            message = "\n".join(msg_lines).strip()
            
            insertions = 0
            deletions = 0
            changed_files = []
            for nline in numstat_lines:
                ins, dels, filepath = nline.split("\t", 2)
                if ins != "-":
                    insertions += int(ins)
                if dels != "-":
                    deletions += int(dels)
                changed_files.append(filepath.strip())
            
            parents = parents_str.split() if parents_str else []
            is_merge = len(parents) > 1
            
            try:
                dt = datetime.fromisoformat(timestamp_str)
            except Exception:
                dt = datetime.utcnow()
                
            commits.append(CommitModel(
                sha=sha,
                short_sha=short_sha,
                message=message,
                author_name=author_name,
                author_email=author_email,
                committer_name=committer_name,
                committer_email=committer_email,
                timestamp=dt,
                parents=parents,
                branch=branch,
                changed_files=changed_files,
                insertions=insertions,
                deletions=deletions,
                is_merge=is_merge
            ))
            
        return commits
