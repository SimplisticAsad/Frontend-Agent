import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import { Alert } from './ui/Alert';

type Variant = 'success' | 'info' | 'danger';
interface Note {
  id: number;
  message: string;
  variant: Variant;
}

const NotifyContext = createContext<((message: string, variant?: Variant) => void) | null>(null);

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notes, setNotes] = useState<Note[]>([]);
  const nextId = useRef(1);

  const notify = useCallback((message: string, variant: Variant = 'success') => {
    const id = nextId.current++;
    setNotes((n) => [...n, { id, message, variant }]);
    window.setTimeout(() => setNotes((n) => n.filter((x) => x.id !== id)), 6000);
  }, []);
  const value = useMemo(() => notify, [notify]);

  return (
    <NotifyContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-4 bottom-4 z-[60] flex flex-col items-center gap-2 sm:inset-x-auto sm:right-4 sm:items-end">
        {notes.map((n) => (
          <Alert key={n.id} variant={n.variant} className="pointer-events-auto w-full shadow-dialog sm:w-80">
            {n.message}
          </Alert>
        ))}
      </div>
    </NotifyContext.Provider>
  );
}

export function useNotify() {
  const ctx = useContext(NotifyContext);
  if (!ctx) throw new Error('useNotify must be used inside <NotificationProvider>');
  return ctx;
}
