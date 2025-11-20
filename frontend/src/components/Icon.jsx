import React from 'react';
// Wrapper to standardize icon sizing & alignment
const Icon = ({ Component, size = 16, className = '', style = {} }) => (
  <span className={`icon ${className}`} style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: size, height: size, lineHeight: 1, ...style }}>
    <Component size={size} />
  </span>
);
export default Icon;
