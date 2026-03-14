import SwiftUI
import UserNotifications

struct SettingsView: View {
    @EnvironmentObject private var settings: AppSettingsStore
    @EnvironmentObject private var notifications: NotificationManager

    var body: some View {
        NavigationStack {
            Form {
                Section("Office Dashboard") {
                    TextField("Office dashboard URL", text: $settings.officeBaseURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                }

                Section("Notifications") {
                    Toggle("Enable alarm notifications later", isOn: $settings.notificationsEnabled)

                    HStack {
                        Text("Permission")
                        Spacer()
                        Text(permissionText)
                            .foregroundStyle(.secondary)
                    }

                    Button("Request Notification Permission") {
                        Task {
                            _ = await notifications.requestPermission()
                        }
                    }
                }

                Section("About") {
                    Text("This app shows the office dashboard, active alarms, and the bore hole in a native layout.")
                    Text("Real alarm push notifications need backend and APNs work later.")
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
        }
    }

    private var permissionText: String {
        switch notifications.authorizationStatus {
        case .authorized, .provisional, .ephemeral:
            return "Allowed"
        case .denied:
            return "Denied"
        case .notDetermined:
            return "Not requested"
        @unknown default:
            return "Unknown"
        }
    }
}
