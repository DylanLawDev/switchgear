import { createBrowserRouter } from "react-router-dom";
import AppShell from "./components/AppShell";
import ChatPage from "./pages/ChatPage";
import SkillsPage from "./pages/SkillsPage";
import WorkflowsPage from "./pages/WorkflowsPage";
import ChannelsPage from "./pages/ChannelsPage";
import ResourcesPage from "./pages/ResourcesPage";
import MemoriesPage from "./pages/MemoriesPage";
import NotFoundPage from "./pages/NotFoundPage";
import SettingsPage from "./pages/SettingsPage";
import SchedulerPage from "./pages/SchedulerPage";
import AgentsPage from "./pages/AgentsPage";
import InboxPage from "./pages/InboxPage";

export const routes = [{
  element: <AppShell />,
  children: [
    { path: "/", element: <ChatPage /> },
    { path: "/skills", element: <SkillsPage /> },
    { path: "/workflows", element: <WorkflowsPage /> },
    { path: "/workflows/:name", element: <WorkflowsPage /> },
    { path: "/scheduler", element: <SchedulerPage /> },
    { path: "/agents", element: <AgentsPage /> },
    { path: "/inbox", element: <InboxPage /> },
    { path: "/channels", element: <ChannelsPage /> },
    { path: "/resources", element: <ResourcesPage /> },
    { path: "/memories", element: <MemoriesPage /> },
    { path: "/settings", element: <SettingsPage /> },
    { path: "*", element: <NotFoundPage /> },
  ],
}];
export const router = createBrowserRouter(routes);
