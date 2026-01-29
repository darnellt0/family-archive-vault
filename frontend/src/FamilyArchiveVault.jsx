import React, { useState, useEffect, useRef } from 'react';
import { 
  Search, 
  Shield, 
  Play, 
  Users, 
  Grid, 
  Clock, 
  Settings, 
  Share2, 
  Lock, 
  Eye, 
  FileVideo, 
  Image as ImageIcon,
  Activity,
  Cpu,
  Database,
  Search as SearchIcon,
  X,
  Check,
  ChevronRight,
  MoreVertical,
  Download,
  Calendar
} from 'lucide-react';

// --- Mock Data (Fallbacks for Demo/Preview Mode) ---

const MOCK_STATS = [
  { label: 'Total Memories', value: '12,450', icon: 'Database', color: 'text-blue-400' },
  { label: 'Faces Indexed', value: '843', icon: 'Users', color: 'text-purple-400' },
  { label: 'Searchable Video', value: '142 hrs', icon: 'FileVideo', color: 'text-emerald-400' },
  { label: 'System Status', value: 'Online', icon: 'Activity', color: 'text-green-400' },
];

const MOCK_RECENT = [
  { id: 1, type: 'video', title: 'Summer Vacation 1998', date: '2 days ago', thumbnail: 'https://images.unsplash.com/photo-1572061486799-da1804e12e79?auto=format&fit=crop&q=80&w=300&h=200' },
  { id: 2, type: 'photo', title: 'Dad at the Beach', date: '3 days ago', thumbnail: 'https://images.unsplash.com/photo-1536768370138-c64dc87198da?auto=format&fit=crop&q=80&w=300&h=200' },
  { id: 3, type: 'photo', title: 'Christmas Dinner', date: '5 days ago', thumbnail: 'https://images.unsplash.com/photo-1543007630-9710e4a00a20?auto=format&fit=crop&q=80&w=300&h=200' },
  { id: 4, type: 'video', title: 'First Steps', date: '1 week ago', thumbnail: 'https://images.unsplash.com/photo-1519689680058-324335c77eba?auto=format&fit=crop&q=80&w=300&h=200' },
];

const MOCK_TRANSCRIPT = [
  { time: '00:04', text: "Okay, looks like it's recording now." },
  { time: '00:08', text: "Look at the camera, say happy birthday!" },
  { time: '00:12', text: "Happy birthday grandma! We miss you so much." },
  { time: '00:15', text: "We're here at the park, it's a beautiful day." },
  { time: '00:19', text: "Wait, don't run too far!" },
  { time: '00:24', text: "[Laughter] She's fast for a toddler." },
  { time: '00:28', text: "Can you believe she's already two?" },
  { time: '00:32', text: "Alright, let's go cut the cake." },
];

const MOCK_SHARES = [
  { id: 1, name: 'Grandma Birthday Album', views: 4, limit: 10, expires: '2023-12-01', active: true },
  { id: 2, name: 'Wedding Raw Footage', views: 1, limit: 5, expires: '2023-11-15', active: true },
  { id: 3, name: 'Old House Photos', views: 12, limit: 50, expires: 'Expired', active: false },
];

// --- Components ---

const SidebarItem = ({ icon: Icon, label, active, onClick, collapsed }) => (
  <button
    onClick={onClick}
    className={`w-full flex items-center p-3 mb-2 rounded-xl transition-all duration-300 group
      ${active 
        ? 'bg-blue-600/20 text-blue-400 shadow-lg shadow-blue-900/20 border border-blue-500/20' 
        : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100'
      }`}
  >
    <Icon size={20} className={`${active ? 'text-blue-400' : 'text-slate-400 group-hover:text-slate-100'}`} />
    {!collapsed && <span className="ml-3 font-medium text-sm">{label}</span>}
    {active && !collapsed && <div className="ml-auto w-1.5 h-1.5 rounded-full bg-blue-400 shadow-glow" />}
  </button>
);

const StatCard = ({ label, value, iconName, color }) => {
  // Map string icon names to Lucide components
  const IconMap = {
    'Database': Database,
    'Users': Users,
    'FileVideo': FileVideo,
    'Activity': Activity
  };
  const Icon = IconMap[iconName] || Activity;

  return (
    <div className="bg-slate-800/50 backdrop-blur-md border border-slate-700/50 p-5 rounded-2xl flex items-center justify-between hover:border-slate-600 transition-all duration-300 group">
      <div>
        <p className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">{label}</p>
        <h3 className="text-2xl font-bold text-slate-100">{value}</h3>
      </div>
      <div className={`p-3 rounded-xl bg-slate-900/50 ${color} group-hover:scale-110 transition-transform duration-300`}>
        <Icon size={24} />
      </div>
    </div>
  );
};

const SearchBar = ({ onSearch }) => (
  <div className="relative w-full max-w-2xl group">
    <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
      <SearchIcon className="h-5 w-5 text-slate-500 group-focus-within:text-blue-400 transition-colors" />
    </div>
    <input
      type="text"
      className="block w-full pl-11 pr-4 py-3 bg-slate-900/80 border border-slate-700/50 rounded-xl leading-5 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 focus:bg-slate-900 transition-all duration-300 sm:text-sm shadow-inner"
      placeholder="Search memories (e.g., 'birthday cake', 'beach sunset', 'whisper transcripts')..."
      onChange={(e) => onSearch(e.target.value)}
    />
    <div className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none">
      <span className="text-slate-600 text-xs border border-slate-700 rounded px-1.5 py-0.5">CMD+K</span>
    </div>
  </div>
);

const MediaCard = ({ item }) => (
  <div className="group relative break-inside-avoid mb-6 rounded-2xl overflow-hidden bg-slate-800 border border-slate-700/50 hover:border-blue-500/30 transition-all duration-300 hover:shadow-2xl hover:shadow-blue-900/10">
    <div className="aspect-w-16 aspect-h-9 relative overflow-hidden">
      <img 
        src={item.thumbnail} 
        onError={(e) => {e.target.src = 'https://images.unsplash.com/photo-1516541196182-6bdb0516ed27?auto=format&fit=crop&q=80&w=300&h=200'}}
        alt={item.title} 
        className="object-cover w-full h-full group-hover:scale-105 transition-transform duration-700 ease-out"
      />
      <div className="absolute inset-0 bg-gradient-to-t from-slate-900 via-transparent to-transparent opacity-0 group-hover:opacity-80 transition-opacity duration-300" />
      
      {/* Type Badge */}
      <div className="absolute top-3 left-3">
        <span className={`px-2 py-1 rounded-lg text-xs font-medium backdrop-blur-md flex items-center gap-1
          ${item.type === 'video' ? 'bg-red-500/20 text-red-200 border border-red-500/20' : 'bg-blue-500/20 text-blue-200 border border-blue-500/20'}`}>
          {item.type === 'video' ? <FileVideo size={10} /> : <ImageIcon size={10} />}
          {item.type === 'video' ? 'Video' : 'Photo'}
        </span>
      </div>

      {/* Play Button Overlay for Video */}
      {item.type === 'video' && (
        <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-300 transform scale-75 group-hover:scale-100">
          <div className="bg-white/10 backdrop-blur-sm p-4 rounded-full border border-white/20 text-white shadow-xl hover:bg-white/20 cursor-pointer">
            <Play fill="currentColor" size={24} />
          </div>
        </div>
      )}
    </div>
    
    <div className="p-4">
      <div className="flex justify-between items-start mb-2">
        <h4 className="text-slate-100 font-semibold truncate pr-2">{item.title}</h4>
        <button className="text-slate-500 hover:text-slate-300 transition-colors">
          <MoreVertical size={16} />
        </button>
      </div>
      <div className="flex items-center text-xs text-slate-500 gap-3">
        <span className="flex items-center gap-1"><Clock size={12} /> {item.date}</span>
      </div>
    </div>
  </div>
);

const VideoPlayer = ({ videoId = 1 }) => {
  const [activeSegment, setActiveSegment] = useState(0);
  const [transcript, setTranscript] = useState([]);
  const scrollRef = useRef(null);

  useEffect(() => {
    // Fetch transcript for specific video
    fetch(`http://localhost:5000/api/transcript/${videoId}`)
      .then(res => res.json())
      .then(data => setTranscript(data))
      .catch(err => {
          console.warn("Error fetching transcript: Running in demo mode", err);
          setTranscript(MOCK_TRANSCRIPT);
      });
  }, [videoId]);

  return (
    <div className="flex flex-col lg:flex-row h-[calc(100vh-140px)] gap-6 overflow-hidden">
      {/* Video Container */}
      <div className="flex-1 bg-black rounded-3xl overflow-hidden relative group shadow-2xl shadow-black/50 border border-slate-800">
        <div className="absolute inset-0 flex items-center justify-center">
            <img 
            src="https://images.unsplash.com/photo-1519689680058-324335c77eba?auto=format&fit=crop&q=80&w=1200" 
            className="w-full h-full object-cover opacity-50" 
            alt="Video placeholder"
          />
          <div className="absolute flex flex-col items-center justify-center text-slate-200">
             <Play className="mx-auto mb-2 opacity-50 bg-white/10 p-4 rounded-full border border-white/20 backdrop-blur-sm" size={64} fill="white" />
          </div>
        </div>
      </div>

      {/* Transcript Sidebar */}
      <div className="w-full lg:w-96 bg-slate-800/50 backdrop-blur-md border border-slate-700/50 rounded-3xl flex flex-col overflow-hidden">
        <div className="p-5 border-b border-slate-700/50 flex justify-between items-center bg-slate-800/80">
          <h3 className="font-semibold text-slate-200 flex items-center gap-2">
            <Activity size={16} className="text-blue-400" />
            Live Transcript
          </h3>
          <Search size={16} className="text-slate-500 cursor-pointer hover:text-slate-300" />
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-1 scrollbar-hide" ref={scrollRef}>
          {transcript.length > 0 ? (
             transcript.map((segment, idx) => (
            <div 
              key={idx}
              onClick={() => setActiveSegment(idx)}
              className={`p-3 rounded-xl cursor-pointer transition-all duration-200 border border-transparent
                ${activeSegment === idx 
                  ? 'bg-blue-600/20 border-blue-500/30 shadow-lg' 
                  : 'hover:bg-slate-700/50 hover:border-slate-600/50'}`}
            >
              <div className="flex gap-3">
                <span className={`text-xs font-mono mt-1 ${activeSegment === idx ? 'text-blue-400' : 'text-slate-500'}`}>
                  {segment.time}
                </span>
                <p className={`text-sm leading-relaxed ${activeSegment === idx ? 'text-blue-100 font-medium' : 'text-slate-400'}`}>
                  {segment.text}
                </p>
              </div>
            </div>
          ))
          ) : (
             <div className="text-center text-slate-500 mt-10 p-4">
                <p>No transcript available for this video.</p>
                <p className="text-xs mt-2">Run whisper_worker.py to generate.</p>
             </div>
          )}
        </div>
      </div>
    </div>
  );
};

const SharingManager = () => {
  const [shares, setShares] = useState([]);

  useEffect(() => {
    fetch('http://localhost:5000/api/shares')
      .then(res => res.json())
      .then(data => setShares(data))
      .catch(err => {
          console.warn("Error fetching shares: Running in demo mode", err);
          setShares(MOCK_SHARES);
      });
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-bold text-slate-100">Access Control</h2>
          <p className="text-slate-400 mt-1">Manage secure links, passwords, and expiration dates.</p>
        </div>
        <button className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-medium shadow-lg shadow-blue-900/20 transition-all flex items-center gap-2">
          <Share2 size={18} />
          New Secure Link
        </button>
      </div>

      <div className="bg-slate-800/50 border border-slate-700/50 rounded-2xl overflow-hidden backdrop-blur-sm">
        <div className="grid grid-cols-12 gap-4 p-4 border-b border-slate-700/50 text-xs font-semibold text-slate-500 uppercase tracking-wider">
          <div className="col-span-4">Shared Resource</div>
          <div className="col-span-2 text-center">Views</div>
          <div className="col-span-2 text-center">Expires</div>
          <div className="col-span-2 text-center">Security</div>
          <div className="col-span-2 text-right">Status</div>
        </div>
        
        {shares.length > 0 ? (
           shares.map((share) => (
          <div key={share.id} className="grid grid-cols-12 gap-4 p-4 items-center hover:bg-slate-800/50 transition-colors border-b border-slate-800/50 last:border-0">
            <div className="col-span-4 flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-blue-900/30 flex items-center justify-center text-blue-400">
                <Share2 size={16} />
              </div>
              <span className="font-medium text-slate-200">{share.name}</span>
            </div>
            
            <div className="col-span-2 flex justify-center">
               <div className="flex items-center gap-2 text-sm text-slate-400 bg-slate-900/50 px-3 py-1 rounded-full border border-slate-700/50">
                  <Eye size={14} />
                  <span>{share.views} / {share.limit}</span>
               </div>
            </div>
            
            <div className="col-span-2 text-center text-sm text-slate-400">
              {share.expires}
            </div>
            
            <div className="col-span-2 flex justify-center gap-2">
              <div className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" title="Password Protected">
                <Lock size={14} />
              </div>
            </div>
            
            <div className="col-span-2 text-right">
               <span className={`px-2 py-1 rounded-md text-xs font-medium border
                 ${share.active 
                   ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' 
                   : 'bg-slate-700/30 text-slate-500 border-slate-600/30'}`}>
                 {share.active ? 'Active' : 'Revoked'}
               </span>
            </div>
          </div>
        ))
        ) : (
            <div className="p-8 text-center text-slate-500">No active shared links found.</div>
        )}
      </div>
    </div>
  );
};

// --- Main App Layout ---

export default function FamilyArchiveVault() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [stats, setStats] = useState([]);
  const [recentItems, setRecentItems] = useState([]);

  // Fetch Data on Mount
  useEffect(() => {
    // 1. Fetch Stats
    fetch('http://localhost:5000/api/stats')
        .then(res => res.json())
        .then(data => {
            setStats(data);
        })
        .catch(err => {
            console.warn("API Error (Stats): Running in demo mode.", err);
            setStats(MOCK_STATS);
        });

    // 2. Fetch Recent
    fetch('http://localhost:5000/api/recent')
        .then(res => res.json())
        .then(data => setRecentItems(data))
        .catch(err => {
            console.warn("API Error (Recent): Running in demo mode.", err);
            setRecentItems(MOCK_RECENT);
        });
  }, []);

  // Dynamic content based on tab
  const renderContent = () => {
    switch(activeTab) {
      case 'dashboard':
        return (
          <div className="space-y-8 animate-in fade-in duration-500">
            {stats.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                {stats.map((stat, idx) => (
                    <StatCard 
                        key={idx} 
                        label={stat.label} 
                        value={stat.value} 
                        iconName={stat.icon} 
                        color={stat.color} 
                    />
                ))}
                </div>
            ) : (
                <div className="text-slate-500">Loading system stats... (Ensure python backend is running)</div>
            )}
            
            <div>
              <div className="flex justify-between items-end mb-6">
                <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
                  <Clock size={20} className="text-blue-400" />
                  Recent Activity
                </h2>
                <button 
                    onClick={() => setActiveTab('gallery')}
                    className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1 transition-colors"
                >
                  View All <ChevronRight size={16} />
                </button>
              </div>
              <div className="columns-1 md:columns-2 lg:columns-4 gap-6 space-y-6">
                {recentItems.length > 0 ? (
                    recentItems.map(item => <MediaCard key={item.id} item={item} />)
                ) : (
                    <p className="text-slate-500">No recent files found in database.</p>
                )}
              </div>
            </div>
          </div>
        );
      case 'video':
        return (
          <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
             <div className="mb-6">
                <h2 className="text-2xl font-bold text-slate-100">Video Player</h2>
                <p className="text-slate-400">Grandma's 80th Birthday • 1998 (Demo)</p>
             </div>
             <VideoPlayer videoId={1} /> 
          </div>
        );
      case 'sharing':
        return (
          <div className="animate-in fade-in duration-500">
            <SharingManager />
          </div>
        );
      case 'gallery':
        return (
          <div className="animate-in fade-in duration-500">
            <div className="flex justify-between items-end mb-6">
               <h2 className="text-2xl font-bold text-slate-100">Gallery</h2>
               <div className="flex gap-2">
                 {['All', 'Photos', 'Videos', 'Favorites'].map(filter => (
                   <button key={filter} className="px-3 py-1.5 text-sm rounded-lg border border-slate-700 hover:border-slate-500 text-slate-400 hover:text-slate-200 transition-all">
                     {filter}
                   </button>
                 ))}
               </div>
            </div>
            <div className="columns-1 sm:columns-2 md:columns-3 lg:columns-4 gap-6 space-y-6">
                {recentItems.map((item, i) => <MediaCard key={i} item={{...item, id: i}} />)}
            </div>
          </div>
        );
      default:
        return <div className="text-slate-400">Section under development</div>;
    }
  };

  return (
    <div className="flex h-screen bg-slate-900 text-slate-100 font-sans selection:bg-blue-500/30">
      {/* Sidebar */}
      <div className={`relative flex flex-col bg-slate-900 border-r border-slate-800 transition-all duration-300 ${sidebarCollapsed ? 'w-20' : 'w-72'}`}>
        <div className="p-6 flex items-center justify-between">
          <div className={`flex items-center gap-3 ${sidebarCollapsed ? 'justify-center w-full' : ''}`}>
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 shadow-lg shadow-blue-500/20 flex items-center justify-center">
              <Shield fill="white" size={18} className="text-white" />
            </div>
            {!sidebarCollapsed && <h1 className="font-bold text-lg tracking-tight bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">FamilyVault</h1>}
          </div>
        </div>

        <nav className="flex-1 px-4 py-4 overflow-y-auto">
          <div className="mb-8">
            {!sidebarCollapsed && <p className="px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider mb-4">Library</p>}
            <SidebarItem icon={Grid} label="Dashboard" active={activeTab === 'dashboard'} onClick={() => setActiveTab('dashboard')} collapsed={sidebarCollapsed} />
            <SidebarItem icon={ImageIcon} label="Gallery" active={activeTab === 'gallery'} onClick={() => setActiveTab('gallery')} collapsed={sidebarCollapsed} />
            <SidebarItem icon={Users} label="Faces" active={activeTab === 'faces'} onClick={() => setActiveTab('faces')} collapsed={sidebarCollapsed} />
            <SidebarItem icon={FileVideo} label="Videos" active={activeTab === 'video'} onClick={() => setActiveTab('video')} collapsed={sidebarCollapsed} />
          </div>

          <div className="mb-8">
            {!sidebarCollapsed && <p className="px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider mb-4">Management</p>}
            <SidebarItem icon={Share2} label="Sharing" active={activeTab === 'sharing'} onClick={() => setActiveTab('sharing')} collapsed={sidebarCollapsed} />
            <SidebarItem icon={Cpu} label="AI Workers" collapsed={sidebarCollapsed} />
            <SidebarItem icon={Settings} label="Settings" collapsed={sidebarCollapsed} />
          </div>
        </nav>
        
        {/* User Profile */}
        <div className="p-4 border-t border-slate-800">
           <div className={`flex items-center gap-3 p-2 rounded-xl hover:bg-slate-800 transition-colors cursor-pointer ${sidebarCollapsed ? 'justify-center' : ''}`}>
             <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center border border-slate-600">
               <span className="text-xs font-bold text-slate-300">AD</span>
             </div>
             {!sidebarCollapsed && (
               <div className="overflow-hidden">
                 <p className="text-sm font-medium text-slate-200">Admin User</p>
                 <p className="text-xs text-slate-500 truncate">admin@familyvault.local</p>
               </div>
             )}
           </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col h-screen overflow-hidden relative">
        {/* Background Gradients */}
        <div className="absolute top-0 left-0 w-full h-96 bg-blue-900/10 blur-[100px] pointer-events-none" />
        
        {/* Top Header */}
        <header className="h-20 px-8 border-b border-slate-800 flex items-center justify-between z-10 bg-slate-900/80 backdrop-blur-xl">
           <SearchBar onSearch={(val) => console.log(val)} />
           <div className="flex items-center gap-4">
             <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-800 border border-slate-700 text-xs text-slate-400">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                System Healthy
             </div>
             <button className="p-2 text-slate-400 hover:text-slate-100 transition-colors">
               <Activity size={20} />
             </button>
           </div>
        </header>

        {/* Scrollable Content */}
        <main className="flex-1 overflow-y-auto p-8 relative z-0 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent">
          {renderContent()}
        </main>
      </div>
    </div>
  );
}