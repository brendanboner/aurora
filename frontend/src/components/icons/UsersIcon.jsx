import React from 'react';
const UsersIcon = ({ size=20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="8" cy="8" r="3" />
    <path d="M2 20c0-3.3 2.7-6 6-6" />
    <circle cx="17" cy="8" r="3" />
    <path d="M13 14c3.3 0 6 2.7 6 6" />
  </svg>
);
export default UsersIcon;