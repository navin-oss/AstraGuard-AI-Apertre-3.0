'use client';

import { useState } from 'react';
import { MissionState } from '../types/dashboard';
import { DashboardHeader } from '../components/dashboard/DashboardHeader';
import { MissionPanel } from '../components/mission/MissionPanel';
import dashboardData from '../mocks/dashboard.json';

import { SystemsPanel } from '../components/systems/SystemsPanel';

import { DashboardProvider, useDashboard } from '../context/DashboardContext';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { TransitionWrapper } from '../components/ui/TransitionWrapper';
import { MobileNavHamburger } from '../components/ui/MobileNavHamburger';

const DashboardContent: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'mission' | 'systems'>('mission');
  const { isConnected } = useDashboard();
  const mission = dashboardData.mission as MissionState;

  return (
    <div className="dashboard-container min-h-screen text-white font-mono antialiased">
      <DashboardHeader data={mission} />

      <div className="flex min-h-screen pt-[100px] lg:pt-[80px] flex-col">
        <nav className="sticky top-[100px] lg:top-[80px] z-20 bg-black/80 backdrop-blur-xl border-b border-teal-500/30 px-6 flex flex-col md:flex-row md:items-center justify-between flex-shrink-0 mb-4" role="tablist">

          {/* Mobile: Vertical Stack (only visible on mobile) */}
          {/* Mobile: Vertical Stack (only visible on mobile) */}
          <MobileNavHamburger activeTab={activeTab} onTabChange={setActiveTab} />

          {/* Desktop: Horizontal (hidden on mobile) */}
          <div className="hidden md:flex gap-2 pt-4">
            <button
              id="mission-tab"
              className={`px-6 py-3 rounded-t-lg font-mono text-lg font-semibold transition-all duration-300 ${activeTab === 'mission'
                ? 'bg-teal-500/10 border-b-2 border-teal-400 text-teal-300 glow-teal'
                : 'text-gray-400 hover:text-teal-300 hover:bg-teal-500/5'
                }`}
              onClick={() => setActiveTab('mission')}
            >
              Mission
            </button>

            <button
              id="systems-tab"
              className={`ml-2 px-6 py-3 rounded-t-lg font-mono text-lg font-semibold transition-all duration-300 ${activeTab === 'systems'
                ? 'bg-cyan-500/10 border-b-2 border-cyan-400 text-cyan-300 glow-cyan'
                : 'text-gray-400 hover:text-cyan-300 hover:bg-cyan-500/5'
                }`}
              onClick={() => setActiveTab('systems')}
            >
              Systems
            </button>
          </div>
        </nav>

        <main className="flex-1 px-6 pb-8 relative">
          {!isConnected ? (
            <LoadingSkeleton type="chart" count={6} />
          ) : (
            <>
              {activeTab === 'mission' && (
                <TransitionWrapper isActive={activeTab === 'mission'}>
                  <MissionPanel />
                </TransitionWrapper>
              )}
              {activeTab === 'systems' && (
                <TransitionWrapper isActive={activeTab === 'systems'}>
                  <SystemsPanel />
                </TransitionWrapper>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
};

const Dashboard: React.FC = () => {
  return (
    <DashboardProvider>
      <DashboardContent />
    </DashboardProvider>
  );
};

export default Dashboard;
