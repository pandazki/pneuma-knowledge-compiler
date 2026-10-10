import worker, { CollectorRegistry as ProductionRegistry } from "../src/index";

// These inspection hooks exist only in the test bundle, never the deployed Worker.
export class CollectorRegistry extends ProductionRegistry {
  #controls: {
    failManifest: boolean;
    blockSnapshot: string | null;
    waiting: boolean;
    release: (() => void) | null;
  };

  constructor(ctx: DurableObjectState, env: Env) {
    const controls = { failManifest: false, blockSnapshot: null as string | null, waiting: false, release: null as (() => void) | null };
    const bucket = new Proxy(env.MATERIALS, {
      get(target, property) {
        if (property === "put") {
          return async (...args: Parameters<R2Bucket["put"]>) => {
            const key = args[0];
            if (controls.failManifest && key.endsWith("/manifest.json")) {
              controls.failManifest = false;
              throw new Error("Synthetic R2 failure");
            }
            const stored = await target.put(...args);
            if (controls.blockSnapshot && key.endsWith(`/${controls.blockSnapshot}/snapshot.json`)) {
              controls.waiting = true;
              await new Promise<void>((resolve) => { controls.release = resolve; });
              controls.waiting = false;
              controls.blockSnapshot = null;
            }
            return stored;
          };
        }
        const value = Reflect.get(target, property, target);
        return typeof value === "function" ? value.bind(target) : value;
      },
    });
    super(ctx, { ...env, MATERIALS: bucket });
    this.#controls = controls;
  }

  failNextManifest() {
    this.#controls.failManifest = true;
  }

  blockUpload(snapshotId: string) {
    this.#controls.blockSnapshot = snapshotId;
  }

  uploadIsBlocked() {
    return this.#controls.waiting;
  }

  releaseUpload() {
    this.#controls.release?.();
  }

  expireInvitations() {
    this.ctx.storage.sql.exec("UPDATE invitations SET expires_at = '2000-01-01T00:00:00.000Z'");
  }

  storedCredentials() {
    return {
      invitations: this.ctx.storage.sql.exec("SELECT token_hash FROM invitations").toArray(),
      devices: this.ctx.storage.sql.exec("SELECT secret_hash FROM devices").toArray(),
    };
  }

  counts() {
    return {
      uploads: this.ctx.storage.sql.exec<{ total: number }>("SELECT count(*) AS total FROM uploads").one().total,
      snapshots: this.ctx.storage.sql.exec<{ total: number }>("SELECT count(*) AS total FROM snapshots").one().total,
    };
  }
}

export default worker;
