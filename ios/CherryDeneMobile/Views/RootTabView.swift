import SwiftUI

struct RootTabView: View {
    @EnvironmentObject private var settings: AppSettingsStore
    @StateObject private var notifications = NotificationManager()

    var body: some View {
        TabView {
            DashboardWebContainer(
                title: "Office",
                subtitle: settings.normalizedURL(settings.officeBaseURL),
                url: settings.officeDashboardURL
            )
            .tabItem { Label("Office", systemImage: "building.2") }

            AlarmFeedView()
                .tabItem { Label("Alarms", systemImage: "bell.badge") }

            DashboardWebContainer(
                title: "Shed",
                subtitle: settings.normalizedURL(settings.shedBaseURL),
                url: settings.shedControllerURL
            )
            .tabItem { Label("Shed", systemImage: "house") }

            DashboardWebContainer(
                title: "Bore Hole",
                subtitle: settings.normalizedURL(settings.boreholeBaseURL),
                url: settings.boreholeControllerURL
            )
            .tabItem { Label("Bore Hole", systemImage: "drop") }

            DashboardWebContainer(
                title: "Farm Health",
                subtitle: settings.normalizedURL(settings.officeBaseURL) + "/farm-health",
                url: settings.officeFarmHealthURL
            )
            .tabItem { Label("Health", systemImage: "cross.case") }

            SettingsView()
                .environmentObject(notifications)
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
        .tint(.green)
        .task {
            await notifications.refreshStatus()
        }
    }
}
