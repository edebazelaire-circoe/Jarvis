import React from 'react';
import {AbsoluteFill} from 'remotion';
export class Boundary extends React.Component<{name: string; children: React.ReactNode}, {error: string | null}> {
  state = {error: null as string | null};
  static getDerivedStateFromError(e: Error) { return {error: String(e && e.message)}; }
  render() {
    if (this.state.error) return <AbsoluteFill style={{background: 'black', color: 'red', fontSize: 24}}>scene {this.props.name} failed: {this.state.error}</AbsoluteFill>;
    return this.props.children;
  }
}
