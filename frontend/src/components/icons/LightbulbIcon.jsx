import React from 'react';
const LightbulbIcon = ({ size = 20, filled = false }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 21h6" />
    <path d="M12 17v4" />
    <path d="M10 17h4" />
    <circle cx="12" cy="9" r="7" fill={filled ? 'currentColor' : 'none'} fillOpacity={filled ? 0.25 : 0} />
    <circle cx="12" cy="9" r="7" />
  </svg>
);
export default LightbulbIcon;