import assert from "node:assert/strict";
import test from "node:test";

import { triggerBlobDownload } from "./download.js";

function replaceGlobal(name, value) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, name);
  Object.defineProperty(globalThis, name, {
    configurable: true,
    writable: true,
    value
  });
  return () => {
    if (descriptor) {
      Object.defineProperty(globalThis, name, descriptor);
      return;
    }
    delete globalThis[name];
  };
}

function createDownloadDocument({ clickError = null } = {}) {
  const appended = [];
  const removed = [];
  const links = [];

  const document = {
    body: {
      appendChild(element) {
        appended.push(element);
      },
      removeChild(element) {
        removed.push(element);
      }
    },
    createElement(tagName) {
      assert.equal(tagName, "a");
      const link = {
        download: "",
        href: "",
        rel: "",
        clickCalls: 0,
        style: {},
        click() {
          this.clickCalls += 1;
          if (clickError) {
            throw clickError;
          }
        }
      };
      links.push(link);
      return link;
    }
  };

  return {
    document,
    get appended() {
      return [...appended];
    },
    get latestLink() {
      return links[links.length - 1] || null;
    },
    get removed() {
      return [...removed];
    }
  };
}

test("triggerBlobDownload creates and revokes an object URL", () => {
  const fakeDocument = createDownloadDocument();
  const urls = [];
  const revoked = [];
  const restoreDocument = replaceGlobal("document", fakeDocument.document);
  const restoreUrl = replaceGlobal("URL", {
    createObjectURL(blob) {
      urls.push(blob);
      return "blob:cad-screenshot";
    },
    revokeObjectURL(url) {
      revoked.push(url);
    }
  });
  const restoreSetTimeout = replaceGlobal("setTimeout", (callback) => {
    callback();
    return 1;
  });

  try {
    const blob = new Blob(["png"], { type: "image/png" });
    const result = triggerBlobDownload(blob, { filename: "cad.png" });

    assert.equal(result.status, "requested");
    assert.equal(result.filename, "cad.png");
    assert.equal(result.message, "Downloading cad.png");
    assert.equal(fakeDocument.latestLink.href, "blob:cad-screenshot");
    assert.equal(fakeDocument.latestLink.download, "cad.png");
    assert.equal(fakeDocument.latestLink.rel, "noopener");
    assert.equal(fakeDocument.latestLink.clickCalls, 1);
    assert.deepEqual(fakeDocument.appended, [fakeDocument.latestLink]);
    assert.deepEqual(fakeDocument.removed, [fakeDocument.latestLink]);
    assert.deepEqual(urls, [blob]);
    assert.deepEqual(revoked, ["blob:cad-screenshot"]);
  } finally {
    restoreSetTimeout();
    restoreUrl();
    restoreDocument();
  }
});

test("triggerBlobDownload surfaces browser click failures and still removes the link", () => {
  const fakeDocument = createDownloadDocument({ clickError: new Error("blocked by test browser") });
  const revoked = [];
  const restoreDocument = replaceGlobal("document", fakeDocument.document);
  const restoreUrl = replaceGlobal("URL", {
    createObjectURL() {
      return "blob:cad-screenshot";
    },
    revokeObjectURL(url) {
      revoked.push(url);
    }
  });
  const restoreSetTimeout = replaceGlobal("setTimeout", (callback) => {
    callback();
    return 1;
  });

  try {
    assert.throws(
      () => triggerBlobDownload(new Blob(["png"]), { filename: "cad.png" }),
      /blocked by test browser/
    );
    assert.deepEqual(fakeDocument.removed, [fakeDocument.latestLink]);
    assert.deepEqual(revoked, ["blob:cad-screenshot"]);
  } finally {
    restoreSetTimeout();
    restoreUrl();
    restoreDocument();
  }
});

test("triggerBlobDownload reports missing object URL support", () => {
  const fakeDocument = createDownloadDocument();
  const restoreDocument = replaceGlobal("document", fakeDocument.document);
  const restoreUrl = replaceGlobal("URL", {});

  try {
    assert.throws(
      () => triggerBlobDownload(new Blob(["png"]), { filename: "cad.png" }),
      /Downloads are not available/
    );
  } finally {
    restoreUrl();
    restoreDocument();
  }
});
