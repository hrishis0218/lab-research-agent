"""Collision-safe, journalled library moves with crash reconciliation and undo."""

from pathlib import Path
import os
import re
from backend.documents.audit import sha256_file


class Organiser:
    def __init__(self, library):
        self.library = library
        with library.write() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS moves(id INTEGER PRIMARY KEY, old TEXT NOT NULL, new TEXT NOT NULL, hash TEXT NOT NULL, state TEXT NOT NULL, error TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS organisation_hold(hash TEXT PRIMARY KEY);""")
        self.recover()

    def safe(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.library.folder):
            raise ValueError("Path outside library")
        return path

    def bind(self, db, old, new, digest):
        st = new.stat()
        db.execute("UPDATE files SET present=0 WHERE path=?", (str(old),))
        db.execute(
            "INSERT OR REPLACE INTO files(path,hash,size,mtime,present) VALUES (?,?,?,?,1)",
            (str(new), digest, st.st_size, st.st_mtime_ns),
        )
        # Stable IDs resolve through attachments; legacy database is never updated.

    def recover(self):
        with self.library.write() as db:
            rows = db.execute(
                "SELECT * FROM moves WHERE state IN ('planned','undo_planned')"
            ).fetchall()
            for row in rows:
                reverse = row["state"] == "undo_planned"
                old = self.safe(row["new"] if reverse else row["old"])
                new = self.safe(row["old"] if reverse else row["new"])
                if (
                    new.is_file()
                    and not old.exists()
                    and sha256_file(new) == row["hash"]
                ):
                    self.bind(db, old, new, row["hash"])
                    db.execute(
                        "UPDATE moves SET state=? WHERE id=?",
                        ("undone" if reverse else "done", row["id"]),
                    )
                elif old.is_file() and not new.exists():
                    db.execute(
                        "UPDATE moves SET state=? WHERE id=?",
                        ("done" if reverse else "cancelled", row["id"]),
                    )
                else:
                    db.execute(
                        "UPDATE moves SET state='needs_attention',error='Ambiguous filesystem state; no files changed' WHERE id=?",
                        (row["id"],),
                    )

    def move(self, path, digest, metadata):
        path = self.safe(path)
        with self.library.write() as db:
            if db.execute(
                "SELECT 1 FROM organisation_hold WHERE hash=?", (digest,)
            ).fetchone():
                return path
        verified = metadata.get("verified", False)
        kind = metadata.get("type", "article")
        groups = {
            "book": "Books",
            "thesis": "Theses",
            "review": "Reviews",
            "report": "Reports",
            "preprint": "Reports",
        }
        group = groups.get(kind, "Articles") if verified else "Needs_Review"
        year = str(metadata.get("year") or "Undated")
        if not re.fullmatch(r"(?:18|19|20)\d{2}|Undated", year):
            year = "Undated"

        def clean(value, length):
            return (
                re.sub(r"[\W_]+", "_", str(value), flags=re.UNICODE)
                .strip("_")[:length]
                .rstrip("_")
            )

        author = clean(
            (
                (metadata.get("authors") or "Unknown")
                .split(";")[0]
                .split(",")[0]
                .strip()
                or "Unknown"
            ).split()[-1],
            22,
        )
        title = clean(metadata.get("title") or path.stem, 85)
        name = f"{year}_{author}_{title}" if verified else f"Unverified_{title}"
        folder = self.library.folder / group
        if group == "Articles":
            folder = folder / year
        folder = self.safe(folder)
        folder.mkdir(parents=True, exist_ok=True)
        target = self.safe(folder / (name + ".pdf"))
        if target == path:
            return path
        if target.exists():
            target = self.safe(folder / (name + "_" + digest[:10] + ".pdf"))
        counter = 1
        while target.exists() and target != path:
            target = self.safe(folder / (name + "_" + digest[:10] + f"_{counter}.pdf"))
            counter += 1
        if target == path:
            return path
        if sha256_file(path) != digest:
            raise ValueError("File changed before organisation")
        with self.library.write() as db:
            operation = db.execute(
                "INSERT INTO moves(old,new,hash,state) VALUES (?,?,?,'planned')",
                (str(path), str(target), digest),
            ).lastrowid
        try:
            # Windows rename fails if destination exists, even if created since collision check.
            if os.name != "nt":
                raise RuntimeError(
                    "Automatic organisation currently requires Windows no-replace rename semantics"
                )
            path.rename(target)
            if sha256_file(target) != digest:
                raise ValueError("Integrity check failed after rename")
            with self.library.write() as db:
                self.bind(db, path, target, digest)
                db.execute("UPDATE moves SET state='done' WHERE id=?", (operation,))
            return target
        except Exception as exc:
            self.recover()
            raise RuntimeError("Organisation deferred; journal retained") from exc

    def undo(self, operation):
        with self.library.write() as db:
            row = db.execute(
                "SELECT * FROM moves WHERE id=? AND state='done'", (operation,)
            ).fetchone()
            if not row:
                raise ValueError("Operation unavailable for undo")
            old = self.safe(row["old"])
            new = self.safe(row["new"])
            if old.exists():
                raise ValueError(
                    "Restore destination already exists; nothing overwritten"
                )
            if not new.is_file() or sha256_file(new) != row["hash"]:
                raise ValueError("Source changed; cannot undo safely")
            db.execute(
                "INSERT OR IGNORE INTO organisation_hold VALUES (?)", (row["hash"],)
            )
            db.execute("UPDATE moves SET state='undo_planned' WHERE id=?", (operation,))
        old.parent.mkdir(parents=True, exist_ok=True)
        new.rename(old)
        if sha256_file(old) != row["hash"]:
            raise ValueError("Restore integrity check failed")
        with self.library.write() as db:
            self.bind(db, new, old, row["hash"])
            db.execute("UPDATE moves SET state='undone' WHERE id=?", (operation,))
        return {"restored": True}

    def restore_all(self):
        with self.library.write() as db:
            operations = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM moves WHERE state='done' ORDER BY id DESC"
                )
            ]
        restored = 0
        blocked = []
        for operation in operations:
            try:
                self.undo(operation)
                restored += 1
            except (ValueError, OSError):
                blocked.append(operation)
        return {"restored_moves": restored, "blocked_operations": blocked}

    def resume(self, document_id):
        import json

        with self.library.write() as db:
            identity = db.execute(
                "SELECT hash,metadata FROM identities WHERE document_id=?",
                (document_id,),
            ).fetchone()
            if not identity:
                raise ValueError("Unknown document")
            paths = [
                Path(r[0])
                for r in db.execute(
                    "SELECT path FROM files WHERE hash=? AND present=1",
                    (identity["hash"],),
                )
            ]
            db.execute(
                "DELETE FROM organisation_hold WHERE hash=?", (identity["hash"],)
            )
        for path in paths:
            self.move(path, identity["hash"], json.loads(identity["metadata"]))
        return {"organised_attachments": len(paths)}
