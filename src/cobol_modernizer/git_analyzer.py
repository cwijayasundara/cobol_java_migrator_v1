from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from git import GitCommandError, Repo

from cobol_modernizer.models import CoChange, GitAuthor


class GitAnalyzer:
    """Extract authorship and co-change patterns from git history."""

    def __init__(self, repo_path: Path) -> None:
        self.repo = Repo(repo_path)

    @staticmethod
    def _changed_files(commit: object, extensions: set[str]) -> list[str]:
        try:
            files = commit.stats.files
        except GitCommandError:
            return []
        return [path for path in files if any(path.endswith(ext) for ext in extensions)]

    def authors(self, extensions: set[str] | None = None) -> list[GitAuthor]:
        if extensions is None:
            extensions = {".py"}
        author_map: dict[str, GitAuthor] = {}
        for commit in self.repo.iter_commits():
            key = commit.author.email or commit.author.name
            if key not in author_map:
                author_map[key] = GitAuthor(
                    name=commit.author.name,
                    email=commit.author.email or "",
                )
            author_map[key].commit_count += 1
            for path in self._changed_files(commit, extensions):
                if path not in author_map[key].files_touched:
                    author_map[key].files_touched.append(path)
        return list(author_map.values())

    def file_authors(self, extensions: set[str] | None = None) -> dict[str, list[str]]:
        """Map each file to the list of author emails that have touched it, ordered by commits."""
        if extensions is None:
            extensions = {".py"}
        file_author_counts: dict[str, Counter[str]] = defaultdict(Counter)
        for commit in self.repo.iter_commits():
            email = commit.author.email or commit.author.name
            for path in self._changed_files(commit, extensions):
                file_author_counts[path][email] += 1
        return {
            path: [author for author, _ in counts.most_common()]
            for path, counts in file_author_counts.items()
        }

    def co_changes(
        self,
        min_times: int = 2,
        extensions: set[str] | None = None,
    ) -> list[CoChange]:
        """Find files that frequently change together in the same commits."""
        if extensions is None:
            extensions = {".py"}
        pair_counts: Counter[tuple[str, str]] = Counter()
        file_counts: Counter[str] = Counter()

        for commit in self.repo.iter_commits():
            files = sorted(self._changed_files(commit, extensions))
            for f in files:
                file_counts[f] += 1
            for a, b in combinations(files, 2):
                pair_counts[(a, b)] += 1

        results: list[CoChange] = []
        for (a, b), count in pair_counts.items():
            if count >= min_times:
                total = file_counts[a] + file_counts[b]
                confidence = (2 * count) / total if total > 0 else 0.0
                results.append(CoChange(
                    file_a=a,
                    file_b=b,
                    times_changed_together=count,
                    confidence=round(confidence, 3),
                ))
        return sorted(results, key=lambda c: c.times_changed_together, reverse=True)
