import SwiftUI

struct RootTabView: View {
    @StateObject private var notifications = NotificationManager()

    var body: some View {
        TabView {
            OfficeOverviewView()
            .tabItem { Label("Office", systemImage: "building.2") }

            AlarmFeedView()
                .tabItem { Label("Alarms", systemImage: "bell.badge") }

            BoreholeOverviewView()
            .tabItem { Label("Bore Hole", systemImage: "drop") }

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
