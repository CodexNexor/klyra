import { Component, type ReactNode } from 'react'

interface Props { children: ReactNode; fallback?: ReactNode }
interface State { hasError: boolean }

export default class ErrorBoundary extends Component<Props, State> {
  state = { hasError: false }

  static getDerivedStateFromError(_error: unknown) { return { hasError: true } }

  render() {
    if (this.state.hasError) return this.props.fallback || null
    return this.props.children
  }
}
