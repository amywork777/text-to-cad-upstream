import { ImportStep } from './import-step';

export function Onboarding({ onComplete }: { onComplete: () => void }) {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center [-webkit-app-region:drag]">
      <div className="mx-auto flex h-full max-h-[70vh] min-h-0 w-full max-w-5xl flex-col items-start justify-center [-webkit-app-region:no-drag]">
        <div className="text-md border border-b-0 bg-background-1 px-5 py-3">Import</div>
        <div className="flex h-full min-h-0 w-full flex-col items-center justify-center border bg-background-1">
          <ImportStep onComplete={onComplete} />
        </div>
      </div>
    </div>
  );
}
