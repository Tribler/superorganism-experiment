from __future__ import annotations

import hashlib
import sqlite3

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from uuid import UUID

from democracy.funding.models import FundingCampaign, FundingPledge
from democracy.models.DTOs.issue_with_votes import IssueWithVotes
from democracy.models.DTOs.solution_with_votes import SolutionWithVotes
from democracy.models.issue import Issue
from democracy.models.issue_vote import IssueVote
from democracy.models.solution import Solution
from democracy.models.solution_vote import SolutionVote
from democracy.models.vote_record_result import VoteRecordResult
from democracy.storage.repository import DemocracyRepository


class SQLiteDemocracyRepository(DemocracyRepository):
    """
    SQLite-backed repository for issues, solutions, and their votes.

    Descriptions are stored as content-addressed text objects. Issues and solutions
    reference their descriptions by SHA-256 hash instead of storing the text directly in
    the issue/solution rows.

    This keeps the protocol objects small and prepares the storage layer for future
    IPFS-like or chunked gossiping.
    """

    def __init__(self, database_path: Path) -> None:
        """
        Create a SQLite democracy repository.

        :param database_path: Path to the SQLite database file.
        :return: None
        """
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(str(database_path))
        self._connection.row_factory = sqlite3.Row

        self._enable_pragmas()
        self._create_schema()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _enable_pragmas(self) -> None:
        """
        Enable useful SQLite settings.

        :return: None
        """
        self._connection.execute("PRAGMA foreign_keys = ON;")
        self._connection.execute("PRAGMA journal_mode = WAL;")

    def _create_schema(self) -> None:
        """
        Create the democracy storage schema if it does not already exist.

        :return: None
        """
        with self._connection:
            self._connection.executescript("""
                CREATE TABLE IF NOT EXISTS content_objects (
                    hash TEXT PRIMARY KEY,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    text_content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS issues (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    creator_id TEXT NOT NULL,
                    description_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,

                    FOREIGN KEY (description_hash)
                        REFERENCES content_objects(hash)
                );

                CREATE TABLE IF NOT EXISTS issue_votes (
                    id TEXT PRIMARY KEY,
                    issue_id TEXT NOT NULL,
                    voter_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,

                    FOREIGN KEY (issue_id)
                        REFERENCES issues(id)
                        ON DELETE CASCADE,

                    UNIQUE (issue_id, voter_id)
                );

                CREATE TABLE IF NOT EXISTS solutions (
                    id TEXT PRIMARY KEY,
                    issue_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    creator_id TEXT NOT NULL,
                    description_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,

                    FOREIGN KEY (issue_id)
                        REFERENCES issues(id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (description_hash)
                        REFERENCES content_objects(hash)
                );

                CREATE TABLE IF NOT EXISTS solution_votes (
                    id TEXT PRIMARY KEY,
                    solution_id TEXT NOT NULL,
                    voter_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,

                    FOREIGN KEY (solution_id)
                        REFERENCES solutions(id)
                        ON DELETE CASCADE,

                    UNIQUE (solution_id, voter_id)
                );
                
                CREATE TABLE IF NOT EXISTS funding_campaigns (
                    id TEXT PRIMARY KEY,
                    solution_id TEXT NOT NULL,
                    solution_hash TEXT NOT NULL,
                    developer_payout_address TEXT NOT NULL,
                    asking_price_sats INTEGER NOT NULL,
                    deadline_height INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                
                    FOREIGN KEY (solution_id)
                        REFERENCES solutions(id)
                        ON DELETE CASCADE,
                
                    UNIQUE(solution_id)
                );
                
                CREATE TABLE IF NOT EXISTS funding_pledges (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    pledger_id TEXT NOT NULL,
                    txid TEXT NOT NULL,
                    vout INTEGER NOT NULL,
                    value_sats INTEGER NOT NULL,
                    signed_pledge_psbt TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                
                    FOREIGN KEY (campaign_id)
                        REFERENCES funding_campaigns(id)
                        ON DELETE CASCADE,
                
                    UNIQUE(campaign_id, txid, vout)
                );

                CREATE INDEX IF NOT EXISTS idx_issue_votes_issue_id
                    ON issue_votes(issue_id);

                CREATE INDEX IF NOT EXISTS idx_issue_votes_voter_issue
                    ON issue_votes(voter_id, issue_id);

                CREATE INDEX IF NOT EXISTS idx_solutions_issue_id
                    ON solutions(issue_id);

                CREATE INDEX IF NOT EXISTS idx_solution_votes_solution_id
                    ON solution_votes(solution_id);

                CREATE INDEX IF NOT EXISTS idx_solution_votes_voter_solution
                    ON solution_votes(voter_id, solution_id);
                
                CREATE INDEX IF NOT EXISTS idx_funding_campaigns_solution_id
                    ON funding_campaigns(solution_id);
                
                CREATE INDEX IF NOT EXISTS idx_funding_pledges_campaign
                    ON funding_pledges(campaign_id);
                
                CREATE INDEX IF NOT EXISTS idx_funding_pledges_outpoint
                    ON funding_pledges(txid, vout);
                """)

    # ------------------------------------------------------------------
    # Content-addressed descriptions
    # ------------------------------------------------------------------

    def _store_text_content(self, text: str) -> str:
        """
        Store a text object by content hash.

        If the same text already exists, it is not inserted again.

        :param text: Text content to store.
        :return: The content hash.
        """
        content_bytes = text.encode("utf-8")
        content_hash = self._compute_content_hash(content_bytes)

        self._connection.execute(
            """
            INSERT OR IGNORE INTO content_objects (
                hash,
                content_type,
                size_bytes,
                text_content,
                created_at
            )
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                content_hash,
                "text/plain; charset=utf-8",
                len(content_bytes),
                text,
                self._utc_now(),
            ),
        )

        return content_hash

    def get_content(self, content_hash: str) -> Optional[str]:
        """
        Retrieve text content by its content hash.

        :param content_hash: The SHA-256 content hash.
        :return: The stored text content, or None if it does not exist.
        """
        row = self._connection.execute(
            """
            SELECT text_content
            FROM content_objects
            WHERE hash = ?;
            """,
            (content_hash,),
        ).fetchone()

        if row is None:
            return None

        return row["text_content"]

    def has_content(self, content_hash: str) -> bool:
        """
        Check whether a content object exists locally.

        :param content_hash: The SHA-256 content hash.
        :return: True if the object exists, otherwise False.
        """
        row = self._connection.execute(
            """
            SELECT 1
            FROM content_objects
            WHERE hash = ?
            LIMIT 1;
            """,
            (content_hash,),
        ).fetchone()

        return row is not None

    @staticmethod
    def _compute_content_hash(content_bytes: bytes) -> str:
        """
        Compute a SHA-256 content hash.

        :param content_bytes: Content bytes.
        :return: A hash string using the format sha256:<hex>.
        """
        digest = hashlib.sha256(content_bytes).hexdigest()
        return f"sha256:{digest}"

    # ------------------------------------------------------------------
    # App read
    # ------------------------------------------------------------------

    def get_all_issues_with_votes(self) -> List[IssueWithVotes]:
        """
        Retrieve all issues along with their vote counts.

        :return: A list of IssueWithVotes instances.
        """
        rows = self._connection.execute("""
            SELECT
                issues.id,
                issues.title,
                issues.creator_id,
                content_objects.text_content AS description,
                issues.created_at,
                COUNT(issue_votes.id) AS vote_count
            FROM issues
            JOIN content_objects
                ON content_objects.hash = issues.description_hash
            LEFT JOIN issue_votes
                ON issue_votes.issue_id = issues.id
            GROUP BY issues.id
            ORDER BY issues.created_at DESC;
            """).fetchall()

        return [
            IssueWithVotes(
                issue=self._row_to_issue(row),
                votes=row["vote_count"],
            )
            for row in rows
        ]

    def get_issue_with_votes(self, issue_id: UUID) -> Optional[IssueWithVotes]:
        """
        Retrieve a specific issue by its ID along with its vote count.

        :param issue_id: The ID of the issue to retrieve.
        :return: An IssueWithVotes instance if found, otherwise None.
        """
        row = self._connection.execute(
            """
            SELECT
                issues.id,
                issues.title,
                issues.creator_id,
                content_objects.text_content AS description,
                issues.created_at,
                COUNT(issue_votes.id) AS vote_count
            FROM issues
            JOIN content_objects
                ON content_objects.hash = issues.description_hash
            LEFT JOIN issue_votes
                ON issue_votes.issue_id = issues.id
            WHERE issues.id = ?
            GROUP BY issues.id;
            """,
            (str(issue_id),),
        ).fetchone()

        if row is None:
            return None

        return IssueWithVotes(
            issue=self._row_to_issue(row),
            votes=row["vote_count"],
        )

    def get_all_solutions_with_votes(self) -> List[SolutionWithVotes]:
        """
        Retrieve all solutions along with their vote counts.

        :return: A list of SolutionWithVotes instances.
        """
        rows = self._connection.execute("""
            SELECT
                solutions.id,
                solutions.issue_id,
                solutions.title,
                solutions.creator_id,
                content_objects.text_content AS description,
                solutions.created_at,
                COUNT(solution_votes.id) AS vote_count
            FROM solutions
            JOIN content_objects
                ON content_objects.hash = solutions.description_hash
            LEFT JOIN solution_votes
                ON solution_votes.solution_id = solutions.id
            GROUP BY solutions.id
            ORDER BY solutions.created_at DESC;
            """).fetchall()

        return [
            SolutionWithVotes(
                solution=self._row_to_solution(row),
                votes=row["vote_count"],
            )
            for row in rows
        ]

    def get_solution_with_votes(self, solution_id: UUID) -> Optional[SolutionWithVotes]:
        """
        Retrieve a specific solution by its ID along with its vote count.

        :param solution_id: The ID of the solution to retrieve.
        :return: A SolutionWithVotes instance if found, otherwise None.
        """
        row = self._connection.execute(
            """
            SELECT
                solutions.id,
                solutions.issue_id,
                solutions.title,
                solutions.creator_id,
                content_objects.text_content AS description,
                solutions.created_at,
                COUNT(solution_votes.id) AS vote_count
            FROM solutions
            JOIN content_objects
                ON content_objects.hash = solutions.description_hash
            LEFT JOIN solution_votes
                ON solution_votes.solution_id = solutions.id
            WHERE solutions.id = ?
            GROUP BY solutions.id;
            """,
            (str(solution_id),),
        ).fetchone()

        if row is None:
            return None

        return SolutionWithVotes(
            solution=self._row_to_solution(row),
            votes=row["vote_count"],
        )

    def get_solutions_for_issue_with_votes(
        self, issue_id: UUID
    ) -> List[SolutionWithVotes]:
        """
        Retrieve all solutions belonging to a specific issue along with vote counts.

        :param issue_id: The ID of the parent issue.
        :return: A list of SolutionWithVotes instances.
        """
        rows = self._connection.execute(
            """
            SELECT
                solutions.id,
                solutions.issue_id,
                solutions.title,
                solutions.creator_id,
                content_objects.text_content AS description,
                solutions.created_at,
                COUNT(solution_votes.id) AS vote_count
            FROM solutions
            JOIN content_objects
                ON content_objects.hash = solutions.description_hash
            LEFT JOIN solution_votes
                ON solution_votes.solution_id = solutions.id
            WHERE solutions.issue_id = ?
            GROUP BY solutions.id
            ORDER BY solutions.created_at DESC;
            """,
            (str(issue_id),),
        ).fetchall()

        return [
            SolutionWithVotes(
                solution=self._row_to_solution(row),
                votes=row["vote_count"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # App write
    # ------------------------------------------------------------------

    def add_issue(self, issue: Issue) -> None:
        """
        Store a new issue.

        :param issue: The issue to store.
        :return: None
        :raises sqlite3.IntegrityError: If the issue ID already exists or
            referenced constraints fail.
        """
        with self._connection:
            description_hash = self._store_text_content(issue.description)

            self._connection.execute(
                """
                INSERT INTO issues (
                    id,
                    title,
                    creator_id,
                    description_hash,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?);
                """,
                (
                    str(issue.id),
                    issue.title,
                    str(issue.creator_id),
                    description_hash,
                    self._datetime_to_storage(issue.created_at),
                ),
            )

    def add_issue_vote(self, vote: IssueVote) -> None:
        """
        Store a vote for an issue.

        :param vote: The issue vote to store.
        :return: None
        :raises sqlite3.IntegrityError: If the vote is duplicate or the issue
            does not exist.
        """
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO issue_votes (
                    id,
                    issue_id,
                    voter_id,
                    created_at
                )
                VALUES (?, ?, ?, ?);
                """,
                (
                    str(vote.id),
                    str(vote.issue_id),
                    str(vote.voter_id),
                    self._datetime_to_storage(vote.created_at),
                ),
            )

    def record_issue_vote(self, vote: IssueVote) -> VoteRecordResult:
        """
        Store a vote for an issue and translate duplicate-vote conflicts into a
        domain result.

        :param vote: The issue vote to store.
        :return: CREATED when stored, ALREADY_VOTED for uniqueness conflicts.
        :raises sqlite3.IntegrityError: If the issue does not exist or another
            integrity constraint fails.
        """
        try:
            self.add_issue_vote(vote)
        except sqlite3.IntegrityError as exc:
            if self._is_duplicate_issue_vote_error(exc):
                return VoteRecordResult.ALREADY_VOTED
            raise

        return VoteRecordResult.CREATED

    def add_solution(self, solution: Solution) -> None:
        """
        Store a new solution.

        :param solution: The solution to store.
        :return: None
        :raises sqlite3.IntegrityError: If the solution ID already exists or
            the parent issue does not exist.
        """
        with self._connection:
            description_hash = self._store_text_content(solution.description)

            self._connection.execute(
                """
                INSERT INTO solutions (
                    id,
                    issue_id,
                    title,
                    creator_id,
                    description_hash,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    str(solution.id),
                    str(solution.issue_id),
                    solution.title,
                    str(solution.creator_id),
                    description_hash,
                    self._datetime_to_storage(solution.created_at),
                ),
            )

    def add_solution_vote(self, vote: SolutionVote) -> None:
        """
        Store a vote for a solution.

        :param vote: The solution vote to store.
        :return: None
        :raises sqlite3.IntegrityError: If the vote is duplicate or the solution
            does not exist.
        """
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO solution_votes (
                    id,
                    solution_id,
                    voter_id,
                    created_at
                )
                VALUES (?, ?, ?, ?);
                """,
                (
                    str(vote.id),
                    str(vote.solution_id),
                    str(vote.voter_id),
                    self._datetime_to_storage(vote.created_at),
                ),
            )

    def record_solution_vote(self, vote: SolutionVote) -> VoteRecordResult:
        """
        Store a vote for a solution and translate duplicate-vote conflicts into a
        domain result.

        :param vote: The solution vote to store.
        :return: CREATED when stored, ALREADY_VOTED for uniqueness conflicts.
        :raises sqlite3.IntegrityError: If the solution does not exist or
            another integrity constraint fails.
        """
        try:
            self.add_solution_vote(vote)
        except sqlite3.IntegrityError as exc:
            if self._is_duplicate_solution_vote_error(exc):
                return VoteRecordResult.ALREADY_VOTED
            raise

        return VoteRecordResult.CREATED

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    def get_issue(self, issue_id: UUID) -> Optional[Issue]:
        """
        Retrieve a specific issue by its ID.

        :param issue_id: The ID of the issue to retrieve.
        :return: The Issue if found, otherwise None.
        """
        row = self._connection.execute(
            """
            SELECT
                issues.id,
                issues.title,
                issues.creator_id,
                content_objects.text_content AS description,
                issues.created_at
            FROM issues
            JOIN content_objects
                ON content_objects.hash = issues.description_hash
            WHERE issues.id = ?;
            """,
            (str(issue_id),),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_issue(row)

    def get_all_issues(self) -> List[Issue]:
        """
        Retrieve all issues.

        :return: A list of Issue instances.
        """
        rows = self._connection.execute("""
            SELECT
                issues.id,
                issues.title,
                issues.creator_id,
                content_objects.text_content AS description,
                issues.created_at
            FROM issues
            JOIN content_objects
                ON content_objects.hash = issues.description_hash
            ORDER BY issues.created_at DESC;
            """).fetchall()

        return [self._row_to_issue(row) for row in rows]

    def get_issue_vote(self, vote_id: UUID) -> Optional[IssueVote]:
        row = self._connection.execute(
            """
            SELECT id, issue_id, voter_id, created_at
            FROM issue_votes
            WHERE id = ?;
            """,
            (str(vote_id),),
        ).fetchone()

        if row is None:
            return None

        return IssueVote(
            id=UUID(row["id"]),
            issue_id=UUID(row["issue_id"]),
            voter_id=UUID(row["voter_id"]),
            created_at=self._datetime_from_storage(row["created_at"]),
        )

    def get_all_issue_votes(self) -> List[IssueVote]:
        rows = self._connection.execute("""
            SELECT id, issue_id, voter_id, created_at
            FROM issue_votes
            ORDER BY created_at DESC;
            """).fetchall()

        return [
            IssueVote(
                id=UUID(row["id"]),
                issue_id=UUID(row["issue_id"]),
                voter_id=UUID(row["voter_id"]),
                created_at=self._datetime_from_storage(row["created_at"]),
            )
            for row in rows
        ]

    def get_solution(self, solution_id: UUID) -> Optional[Solution]:
        """
        Retrieve a specific solution by its ID.

        :param solution_id: The ID of the solution to retrieve.
        :return: The Solution if found, otherwise None.
        """
        row = self._connection.execute(
            """
            SELECT
                solutions.id,
                solutions.issue_id,
                solutions.title,
                solutions.creator_id,
                content_objects.text_content AS description,
                solutions.created_at
            FROM solutions
            JOIN content_objects
                ON content_objects.hash = solutions.description_hash
            WHERE solutions.id = ?;
            """,
            (str(solution_id),),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_solution(row)

    def get_all_solutions(self) -> List[Solution]:
        """
        Retrieve all solutions.

        :return: A list of Solution instances.
        """
        rows = self._connection.execute("""
            SELECT
                solutions.id,
                solutions.issue_id,
                solutions.title,
                solutions.creator_id,
                content_objects.text_content AS description,
                solutions.created_at
            FROM solutions
            JOIN content_objects
                ON content_objects.hash = solutions.description_hash
            ORDER BY solutions.created_at DESC;
            """).fetchall()

        return [self._row_to_solution(row) for row in rows]

    def get_solution_vote(self, vote_id: UUID) -> Optional[SolutionVote]:
        row = self._connection.execute(
            """
            SELECT id, solution_id, voter_id, created_at
            FROM solution_votes
            WHERE id = ?;
            """,
            (str(vote_id),),
        ).fetchone()

        if row is None:
            return None

        return SolutionVote(
            id=UUID(row["id"]),
            solution_id=UUID(row["solution_id"]),
            voter_id=UUID(row["voter_id"]),
            created_at=self._datetime_from_storage(row["created_at"]),
        )

    def get_all_solution_votes(self) -> List[SolutionVote]:
        rows = self._connection.execute("""
            SELECT id, solution_id, voter_id, created_at
            FROM solution_votes
            ORDER BY created_at DESC;
            """).fetchall()

        return [
            SolutionVote(
                id=UUID(row["id"]),
                solution_id=UUID(row["solution_id"]),
                voter_id=UUID(row["voter_id"]),
                created_at=self._datetime_from_storage(row["created_at"]),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Additional storage operations
    # ------------------------------------------------------------------

    def replace_issue(self, issue_id: UUID, issue: Issue) -> bool:
        """
        Replace an existing issue.

        :param issue_id: The ID of the issue to replace.
        :param issue: The new issue data.
        :return: True if the issue was replaced, otherwise False.
        """
        with self._connection:
            description_hash = self._store_text_content(issue.description)

            cursor = self._connection.execute(
                """
                UPDATE issues
                SET
                    id = ?,
                    title = ?,
                    creator_id = ?,
                    description_hash = ?,
                    created_at = ?
                WHERE id = ?;
                """,
                (
                    str(issue.id),
                    issue.title,
                    str(issue.creator_id),
                    description_hash,
                    self._datetime_to_storage(issue.created_at),
                    str(issue_id),
                ),
            )

        return cursor.rowcount > 0

    def delete_issue(self, issue_id: UUID) -> bool:
        """
        Delete an issue.

        Related solutions and votes are deleted through cascading foreign keys.

        :param issue_id: The ID of the issue to delete.
        :return: True if the issue was deleted, otherwise False.
        """
        with self._connection:
            cursor = self._connection.execute(
                """
                DELETE FROM issues
                WHERE id = ?;
                """,
                (str(issue_id),),
            )

        return cursor.rowcount > 0

    def replace_solution(self, solution_id: UUID, solution: Solution) -> bool:
        """
        Replace an existing solution.

        :param solution_id: The ID of the solution to replace.
        :param solution: The new solution data.
        :return: True if the solution was replaced, otherwise False.
        """
        with self._connection:
            description_hash = self._store_text_content(solution.description)

            cursor = self._connection.execute(
                """
                UPDATE solutions
                SET
                    id = ?,
                    issue_id = ?,
                    title = ?,
                    creator_id = ?,
                    description_hash = ?,
                    created_at = ?
                WHERE id = ?;
                """,
                (
                    str(solution.id),
                    str(solution.issue_id),
                    solution.title,
                    str(solution.creator_id),
                    description_hash,
                    self._datetime_to_storage(solution.created_at),
                    str(solution_id),
                ),
            )

        return cursor.rowcount > 0

    def delete_solution(self, solution_id: UUID) -> bool:
        """
        Delete a solution.

        Related solution votes are deleted through cascading foreign keys.

        :param solution_id: The ID of the solution to delete.
        :return: True if the solution was deleted, otherwise False.
        """
        with self._connection:
            cursor = self._connection.execute(
                """
                DELETE FROM solutions
                WHERE id = ?;
                """,
                (str(solution_id),),
            )

        return cursor.rowcount > 0

    def get_solutions_for_issue(self, issue_id: UUID) -> List[Solution]:
        """
        Retrieve all solutions belonging to a specific issue.

        :param issue_id: The ID of the parent issue.
        :return: A list of Solution instances.
        """
        rows = self._connection.execute(
            """
            SELECT
                solutions.id,
                solutions.issue_id,
                solutions.title,
                solutions.creator_id,
                content_objects.text_content AS description,
                solutions.created_at
            FROM solutions
            JOIN content_objects
                ON content_objects.hash = solutions.description_hash
            WHERE solutions.issue_id = ?
            ORDER BY solutions.created_at DESC;
            """,
            (str(issue_id),),
        ).fetchall()

        return [self._row_to_solution(row) for row in rows]

    # ------------------------------------------------------------------
    # Funding campaigns
    # ------------------------------------------------------------------

    def add_campaign(self, campaign: FundingCampaign) -> None:
        """
        Store a funding campaign.

        :param campaign: The funding campaign to store.
        :return: None
        :raises sqlite3.IntegrityError: If the campaign ID already exists, if a campaign
            already exists for the solution, or if the referenced solution does not exist.
        """
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO funding_campaigns (
                    id,
                    solution_id,
                    solution_hash,
                    developer_payout_address,
                    asking_price_sats,
                    deadline_height,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    str(campaign.id),
                    str(campaign.solution_id),
                    campaign.solution_hash,
                    campaign.developer_payout_address,
                    campaign.asking_price_sats,
                    campaign.deadline_height,
                    self._datetime_to_storage(campaign.created_at),
                ),
            )

    def get_campaign(self, campaign_id: UUID) -> Optional[FundingCampaign]:
        """
        Retrieve a funding campaign by its ID.

        :param campaign_id: The campaign ID.
        :return: The funding campaign if found, otherwise None.
        """
        row = self._connection.execute(
            """
            SELECT *
            FROM funding_campaigns
            WHERE id = ?;
            """,
            (str(campaign_id),),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_campaign(row)

    def get_campaign_for_solution(
        self,
        solution_id: UUID,
    ) -> Optional[FundingCampaign]:
        """
        Retrieve the funding campaign for a solution.

        :param solution_id: The solution ID.
        :return: The funding campaign if one exists, otherwise None.
        """
        row = self._connection.execute(
            """
            SELECT *
            FROM funding_campaigns
            WHERE solution_id = ?;
            """,
            (str(solution_id),),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_campaign(row)

    def get_all_campaigns(self) -> List[FundingCampaign]:
        """
        Retrieve all funding campaigns.

        :return: List of funding campaigns.
        """
        rows = self._connection.execute("""
            SELECT *
            FROM funding_campaigns
            ORDER BY created_at DESC;
            """).fetchall()

        return [self._row_to_campaign(row) for row in rows]

    # ------------------------------------------------------------------
    # Funding pledges
    # ------------------------------------------------------------------

    def add_pledge(self, pledge: FundingPledge) -> None:
        """
        Store a funding pledge.

        :param pledge: The funding pledge to store.
        :return: None
        :raises sqlite3.IntegrityError: If the pledge ID already exists, if the same
            outpoint was already pledged for the campaign, or if the campaign does not
            exist.
        """
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO funding_pledges (
                    id,
                    campaign_id,
                    pledger_id,
                    txid,
                    vout,
                    value_sats,
                    signed_pledge_psbt,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    str(pledge.id),
                    str(pledge.campaign_id),
                    str(pledge.pledger_id),
                    pledge.txid,
                    pledge.vout,
                    pledge.value_sats,
                    pledge.signed_pledge_psbt,
                    self._datetime_to_storage(pledge.created_at),
                ),
            )

    def get_pledge(self, pledge_id: UUID) -> Optional[FundingPledge]:
        """
        Retrieve a funding pledge by its ID.

        :param pledge_id: The pledge ID.
        :return: The funding pledge if found, otherwise None.
        """
        row = self._connection.execute(
            """
            SELECT *
            FROM funding_pledges
            WHERE id = ?;
            """,
            (str(pledge_id),),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_pledge(row)

    def get_pledges_for_campaign(
        self,
        campaign_id: UUID,
    ) -> List[FundingPledge]:
        """
        Retrieve all pledges for a funding campaign.

        :param campaign_id: The campaign ID.
        :return: List of funding pledges for the campaign.
        """
        rows = self._connection.execute(
            """
            SELECT *
            FROM funding_pledges
            WHERE campaign_id = ?
            ORDER BY created_at ASC;
            """,
            (str(campaign_id),),
        ).fetchall()

        return [self._row_to_pledge(row) for row in rows]

    def get_all_pledges(self) -> List[FundingPledge]:
        """
        Retrieve all funding pledges.

        :return: List of funding pledges.
        """
        rows = self._connection.execute("""
            SELECT *
            FROM funding_pledges
            ORDER BY created_at DESC;
            """).fetchall()

        return [self._row_to_pledge(row) for row in rows]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """
        Close the underlying SQLite connection.

        :return: None
        """
        self._connection.close()

    @staticmethod
    def _is_duplicate_issue_vote_error(error: sqlite3.IntegrityError) -> bool:
        message = str(error)
        return (
            "UNIQUE constraint failed" in message
            and "issue_votes.issue_id" in message
            and "issue_votes.voter_id" in message
        )

    @staticmethod
    def _is_duplicate_solution_vote_error(error: sqlite3.IntegrityError) -> bool:
        message = str(error)
        return (
            "UNIQUE constraint failed" in message
            and "solution_votes.solution_id" in message
            and "solution_votes.voter_id" in message
        )

    # ------------------------------------------------------------------
    # Row mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_issue(row: sqlite3.Row) -> Issue:
        """
        Convert a SQLite row to an Issue model.

        :param row: SQLite row.
        :return: Issue instance.
        """
        return Issue(
            id=UUID(row["id"]),
            title=row["title"],
            creator_id=UUID(row["creator_id"]),
            description=row["description"],
            created_at=SQLiteDemocracyRepository._datetime_from_storage(
                row["created_at"]
            ),
        )

    @staticmethod
    def _row_to_solution(row: sqlite3.Row) -> Solution:
        """
        Convert a SQLite row to a Solution model.

        :param row: SQLite row.
        :return: Solution instance.
        """
        return Solution(
            id=UUID(row["id"]),
            issue_id=UUID(row["issue_id"]),
            title=row["title"],
            creator_id=UUID(row["creator_id"]),
            description=row["description"],
            created_at=SQLiteDemocracyRepository._datetime_from_storage(
                row["created_at"]
            ),
        )

    @staticmethod
    def _row_to_campaign(row: sqlite3.Row) -> FundingCampaign:
        """
        Convert a SQLite row to a FundingCampaign model.

        :param row: SQLite row.
        :return: FundingCampaign instance.
        """
        return FundingCampaign(
            id=UUID(row["id"]),
            solution_id=UUID(row["solution_id"]),
            solution_hash=row["solution_hash"],
            developer_payout_address=row["developer_payout_address"],
            asking_price_sats=int(row["asking_price_sats"]),
            deadline_height=int(row["deadline_height"]),
            created_at=SQLiteDemocracyRepository._datetime_from_storage(
                row["created_at"]
            ),
        )

    @staticmethod
    def _row_to_pledge(row: sqlite3.Row) -> FundingPledge:
        """
        Convert a SQLite row to a FundingPledge model.

        :param row: SQLite row.
        :return: FundingPledge instance.
        """
        return FundingPledge(
            id=UUID(row["id"]),
            campaign_id=UUID(row["campaign_id"]),
            pledger_id=UUID(row["pledger_id"]),
            txid=row["txid"],
            vout=int(row["vout"]),
            value_sats=int(row["value_sats"]),
            signed_pledge_psbt=row["signed_pledge_psbt"],
            created_at=SQLiteDemocracyRepository._datetime_from_storage(
                row["created_at"]
            ),
        )

    # ------------------------------------------------------------------
    # Date helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _utc_now() -> str:
        """
        Return the current UTC time as an ISO-8601 string.

        :return: Current UTC time.
        """
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _datetime_to_storage(value: Any) -> str:
        """
        Convert a datetime-like value to a string for storage.

        :param value: A datetime or string-like value.
        :return: ISO-8601-compatible string.
        """
        if isinstance(value, datetime):
            return value.isoformat()

        return str(value)

    @staticmethod
    def _datetime_from_storage(value: str) -> Any:
        """
        Convert a stored datetime string back to a datetime object when possible.

        :param value: Stored datetime string.
        :return: datetime object if parsing succeeds, otherwise the original string.
        """
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
