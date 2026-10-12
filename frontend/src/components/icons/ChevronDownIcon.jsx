import React from 'react';

const ChevronDownIcon = ({ size = 24, style = {} }) => (
  <svg 
    width={size} 
    height={size} 
    viewBox="0 0 24 24" 
    fill="none" 
    stroke="currentColor" 
    strokeWidth="2" 
    strokeLinecap="round" 
    strokeLinejoin="round" 
    style={style}
  >
    <polyline points="6,9 12,15 18,9"></polyline>
  </svg>
);

export default ChevronDownIcon;