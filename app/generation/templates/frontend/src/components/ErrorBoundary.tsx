import { Component, type ErrorInfo, type ReactNode } from 'react';
import { ErrorState } from './ui/States';

interface State {
  failed: boolean;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Diagnostics go to the console only; users never see stack traces.
    console.error('Unhandled UI error', error.message, info.componentStack);
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="mx-auto max-w-lg p-6">
          <ErrorState message="An unexpected error occurred. Reload the page to continue." onRetry={() => window.location.reload()} />
        </div>
      );
    }
    return this.props.children;
  }
}
