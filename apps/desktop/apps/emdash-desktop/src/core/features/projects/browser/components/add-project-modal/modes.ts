import { useState } from 'react';

export function usePickMode() {
  const [path, setPath] = useState('');
  const [initGitRepository, setinitGitRepository] = useState<boolean>(false);

  const handlePathChange = (newPath: string) => {
    setPath(newPath);
    setinitGitRepository(false);
  };

  const isValid = path.trim().length > 0;

  return {
    path,
    initGitRepository,
    setinitGitRepository,
    handlePathChange,
    isValid,
  };
}

export type PickModeState = ReturnType<typeof usePickMode>;
