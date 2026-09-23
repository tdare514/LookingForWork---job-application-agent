// A D1-shaped wrapper over node:sqlite, so tests run the real SQL.
//
// node:sqlite, like D1, refuses a statement bound with the wrong number of
// values -- which is exactly the class of bug a mocked database would hide.
import { readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import type { DatabaseSync as DatabaseSyncType, SQLInputValue } from "node:sqlite";

// Vite's resolver predates node:sqlite; load it through Node directly.
const { DatabaseSync } = createRequire(import.meta.url)("node:sqlite") as typeof import("node:sqlite");

class Statement {
  constructor(
    private readonly db: DatabaseSyncType,
    readonly sql: string,
    readonly values: SQLInputValue[] = [],
  ) {}

  bind(...values: SQLInputValue[]): Statement {
    return new Statement(this.db, this.sql, values);
  }

  async first<T>(): Promise<T | null> {
    return (this.db.prepare(this.sql).get(...this.values) as T | undefined) ?? null;
  }

  async all<T>(): Promise<{ results: T[] }> {
    return { results: this.db.prepare(this.sql).all(...this.values) as T[] };
  }

  async run(): Promise<{ meta: { changes: number } }> {
    return this.execute();
  }

  execute(): { meta: { changes: number } } {
    const result = this.db.prepare(this.sql).run(...this.values);
    return { meta: { changes: Number(result.changes) } };
  }
}

export class TestD1 {
  readonly db: DatabaseSyncType = new DatabaseSync(":memory:");

  constructor() {
    const dir = join(import.meta.dirname, "..", "migrations");
    for (const file of readdirSync(dir).filter((name) => name.endsWith(".sql")).sort()) {
      this.db.exec(readFileSync(join(dir, file), "utf8"));
    }
  }

  prepare(sql: string): Statement {
    return new Statement(this.db, sql);
  }

  // D1 runs a batch as one transaction: all of it or none of it.
  async batch(statements: Statement[]): Promise<{ meta: { changes: number } }[]> {
    this.db.exec("BEGIN");
    try {
      const results = statements.map((statement) => statement.execute());
      this.db.exec("COMMIT");
      return results;
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  asD1(): D1Database {
    return this as unknown as D1Database;
  }
}
