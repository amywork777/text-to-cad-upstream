import { toast } from '@emdash/ui/react/primitives';
import { observer } from 'mobx-react-lite';
import { useEffect, useRef } from 'react';
import { getBrowserClient } from '@core/features/browser/api/browser/client';
import type { CadTabResource } from '@core/features/cad/api/browser/cad-tab-resource';
import {
  hasWorkbenchChatInputSubscriber,
  publishWorkbenchChatInput,
} from '@core/features/conversations/api/browser/chat/workbench-chat-input-bridge';
import type { TaskTabContext } from '@core/features/workbench/api/browser/tabs/task-tab-context';
import { usePaneContext } from '@core/primitives/workbench-shell/browser/tabs/pane-context';
import { captureCadScreenshotForWorkbenchChat } from './cad-workbench-chat-workflow';
import { useCadWorkbenchLifecycle } from './use-cad-workbench-lifecycle';

/**
 * Relays viewer-local selections and captures into the normal task chat.
 * The CAD iframe never owns a second composer in the workbench layout.
 */
export const CadWorkbenchChatRelay = observer(function CadWorkbenchChatRelay({
  resource,
  task,
  sourcePath,
}: {
  resource: CadTabResource;
  task: TaskTabContext;
  sourcePath: string | null;
}) {
  const { isFocusedPane } = usePaneContext();
  const handledCaptureRequest = useRef(resource.captureRequest);
  const mounted = useRef(true);

  useCadWorkbenchLifecycle({ resource, task, sourcePath, focused: isFocusedPane });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    let consuming = false;
    const consumeReference = async () => {
      if (consuming) return;
      const target = { projectId: task.projectId, taskId: task.taskId };
      if (!hasWorkbenchChatInputSubscriber(target)) return;
      consuming = true;
      try {
        const command = await resource.consumeViewerReferenceCommand();
        if (!mounted.current || !command) return;
        await publishWorkbenchChatInput(target, {
          kind: 'reference',
          reference: command.reference,
        });
      } finally {
        consuming = false;
      }
    };
    void consumeReference();
    const timer = window.setInterval(() => void consumeReference(), 350);
    return () => window.clearInterval(timer);
  }, [resource, task.projectId, task.taskId]);

  useEffect(() => {
    const request = resource.captureRequest;
    if (request <= handledCaptureRequest.current) return;
    handledCaptureRequest.current = request;
    void (async () => {
      const result = await captureCadScreenshotForWorkbenchChat({
        target: { projectId: task.projectId, taskId: task.taskId },
        capture: async () =>
          (await getBrowserClient()).captureScreenshotForChat({ browserId: resource.browserId }),
      });
      if (!mounted.current) return;
      if (!result.success) {
        toast.error('Could not add screenshot to chat', {
          description: result.error,
        });
        return;
      }
      toast('Screenshot copied and added to chat');
    })().catch((error: unknown) => {
      if (!mounted.current) return;
      toast.error(error instanceof Error ? error.message : 'Could not capture the model.');
    });
  }, [resource, resource.captureRequest, task.projectId, task.taskId]);

  return null;
});
