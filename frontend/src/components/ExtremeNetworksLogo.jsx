import React from 'react';

const ExtremeNetworksLogo = ({ height = 36, width = 36 }) => {
  const src = '/octo_logo.png';
  return (
    <img
      src={src}
      alt="Octo Aurora"
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
