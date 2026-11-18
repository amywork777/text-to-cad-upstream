import { useState } from "react";
import { Button } from "@cad/ui/primitives/button";

/**
 * A project whose custom features are code it carries (`cad.build123d.feature`), not yet trusted: its code has
 * not run, as a document's macros do not run as it opens. The prompt names each file and the features it
 * declares, and Trust and run trusts that code as it is now (`useEditMode`'s `trustProject`, kept per project
 * by a hash of those files: changed, it asks again). Not now leaves the part unread and the prompt folded to a
 * line that opens it again. Trusting is no sandbox: the code then runs with the person's own permissions, and
 * the prompt says so. A notice of the view's top-right corner (`RendererShell`'s `notice`), as
 * `ImportedBody` is.
 *
 * @param {{ trust: { digest: string, files: { file: string, features: string[] }[], changed?: boolean, declined?: boolean },
 *   onTrust: () => Promise<boolean>, onDecline: () => void, onReview: () => void }} props
 */
export default function TrustPrompt({ trust, onTrust, onDecline, onReview }) {
  const [busy, setBusy] = useState(false);
  const files = trust.files || [];
  if (trust.declined) {
    return <div data-cad-trust-prompt="declined" className="flex items-center justify-between gap-2 rounded-md border border-border bg-background px-2 py-1.5 text-xs shadow-sm">
      <span className="min-w-0 truncate text-muted-foreground">Custom code features not run</span>
      <Button size="xs" variant="outline" onClick={onReview}>Review</Button>
    </div>;
  }
  const run = async () => {
    setBusy(true);
    try { await onTrust(); } finally { setBusy(false); }
  };
  return <div data-cad-trust-prompt="" role="alertdialog" aria-labelledby="cad-trust-title" aria-describedby="cad-trust-words"
    className="flex max-w-80 flex-col gap-2 rounded-md border border-warning-border bg-background px-3 py-2.5 text-xs shadow-sm">
    <div id="cad-trust-title" className="font-medium text-foreground">
      {trust.changed ? "This project's custom code features changed. Trust and run?" : "This project contains custom code features. Trust and run?"}
    </div>
    <div id="cad-trust-words" className="text-muted-foreground">
      Custom features are Python the project carries. None of it has run. Trusted, it runs with your permissions, as any
      script you run does: trust only a project you know.
    </div>
    <ul className="flex flex-col gap-0.5" data-cad-trust-files="">
      {files.map(each => <li key={each.file} className="min-w-0 truncate" title={`${each.file}: ${each.features.join(", ")}`}>
        <span className="font-mono text-foreground">{each.file}</span>
        <span className="text-muted-foreground"> · {each.features.join(", ")}</span>
      </li>)}
    </ul>
    <div className="flex justify-end gap-1.5">
      <Button size="xs" variant="outline" disabled={busy} onClick={onDecline}>Not now</Button>
      <Button size="xs" disabled={busy} onClick={() => void run()}>{busy ? "Running" : "Trust and run"}</Button>
    </div>
  </div>;
}
