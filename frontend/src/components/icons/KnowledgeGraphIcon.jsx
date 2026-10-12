import React from 'react';
const KnowledgeGraphIcon = ({ size=20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="5" cy="12" r="3" />
    <circle cx="19" cy="5" r="3" />
    <circle cx="19" cy="19" r="3" />
    <path d="M8 12h8" />
    <path d="M17 7l-7 5" />
    <path d="M17 17l-7-5" />
  </svg>
);
export default KnowledgeGraphIcon;