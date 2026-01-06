'use client';

import { useState, useEffect } from 'react';
import { MissionState } from '../../types/dashboard';
import { useDashboard } from '../../context/DashboardContext';

interface Props {
  data: MissionState;
}

const statusIcon = (status: MissionState['status']) => {
  const icons = { Nominal: '🟢', Degraded: '🟡', Critical: '🔴' };
  return icons[status];
};

export const DashboardHeader: React.FC<Props> = ({ data }) => {
  const { isConnected } = useDashboard();
  const [time, setTime] = useState(new Date().toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Kolkata',
  }));

  useEffect(() => {
    const iv = setInterval(
      () =>
        setTime(
          new Date().toLocaleTimeString('en-IN', {
            hour: '2-digit',
            minute: '2-digit',
          })
        ),
      1000 * 30
    );
    return () => clearInterval(iv);
  }, []);

  return (
    <header className="h-[100px] lg:h-[80px] bg-black/90 backdrop-blur-2xl border-b border-teal-500/50 flex items-center px-6 fixed w-full z-50 shadow-2xl shadow-teal-500/10">
      {/* Critical: 3-sec scan path */}
      <div className="flex items-center space-x-6 w-full">
        {/* MISSION STATUS - PRIMARY (32px) */}
        <div className="flex items-center space-x-4 min-w-0 flex-shrink-0">
          <div className="w-16 h-16 bg-gradient-to-br from-teal-500/80 to-cyan-500/80 rounded-2xl glow-teal animate-pulse-slow shadow-2xl" />
          <div className="min-w-0">
            <h1 className="text-3xl lg:text-2xl font-black font-mono text-white tracking-tight truncate">{data.name}</h1>
            <div className="flex items-center space-x-4 mt-1">
              <span className="px-4 py-2 bg-gray-900/80 text-lg rounded-full text-teal-400 glow-teal font-mono font-bold border border-teal-500/50">
                {data.phase}
              </span>
              <span className="text-3xl">{statusIcon(data.status)}</span>
            </div>
          </div>
        </div>

        {/* CONNECTION STATUS - SECONDARY */}
        <div className="flex items-center space-x-4 ml-auto">
          <span className={`px-4 py-2 rounded-full text-sm font-mono font-bold border ${isConnected
              ? 'bg-green-500/20 text-green-400 border-green-400/50 glow-green animate-pulse-slow'
              : 'bg-red-500/20 text-red-400 border-red-400/50 glow-red'
            }`}>
            {isConnected ? '🟢 LIVE' : '🔴 OFFLINE'}
          </span>
          <span className="text-lg font-mono opacity-80">{time}</span>
        </div>
      </div>
    </header>
  );
};
