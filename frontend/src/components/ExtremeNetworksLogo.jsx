import React from 'react';

const ExtremeNetworksLogo = ({ height = 36, width = 36 }) => {
  const src = 'https://avatars.githubusercontent.com/u/8524391';
  return (
    <img
      src={src}
      alt="Extreme Networks"
      height={height}
      width={width}
      style={{
        display: 'block',
        borderRadius: 6,
        backgroundColor: 'transparent',
        objectFit: 'cover'
      }}
    />
  );
};

export default ExtremeNetworksLogo;
