import React from 'react';
const CollapseIcon = ({ size=20, collapsed }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" style={{transform: collapsed? 'rotate(180deg)' : 'none', transition:'transform .3s'}}>
    <path d="M8 9l4 4 4-4" />
  </svg>
);
export default CollapseIcon;