import React from 'react';
const TrashIcon = ({ size=16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 6h18" />
    <path d="M8 6l1-2h6l1 2" />
    <path d="M6 6v14h12V6" />
    <path d="M10 10v6" />
    <path d="M14 10v6" />
  </svg>
);
export default TrashIcon;