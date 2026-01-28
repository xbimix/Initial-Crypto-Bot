import ControlPanel from "./components/ControlPanel";
import ConfigForm from "./components/ConfigForm";
import StatusCard from "./components/StatusCard";
import KillSwitch from "./components/KillSwitch";
import LiveTradingToggle from "./components/LiveTradingToggle";




export default function Page() {
  return (
    <main className="space-y-8">
      <h1 className="text-2xl font-bold">RevBot Dashboard</h1>
      
      <StatusCard />
      <ControlPanel />
      <ConfigForm />
      
       <KillSwitch />
      <LiveTradingToggle />

      
    </main>



  );
}
